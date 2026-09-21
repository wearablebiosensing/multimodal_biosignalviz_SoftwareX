import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import scipy.signal as signal
import scipy.stats as stats
import neurokit2 as nk
import wfdb
import bioread
import tempfile
import zipfile
import os
import shutil
import time
import traceback
import uuid
import gc
import warnings
import json
import sys
import math
try:
    import resource  # POSIX only; used for peak-memory reporting in the benchmark
except ImportError:
    resource = None
from machine_learning.RF.ml_random_forest import rf_leave_one_participant_out_weighted #rf_leave_one_participant_out_undersampled
from machine_learning.SVM.ml_svm import svm_leave_one_participant_out_weighted
from machine_learning.DT.ml_dt import dt_leave_one_participant_out
from machine_learning.GB.ml_gb import gb_leave_one_participant_out
from processing_helpers import *
warnings.simplefilter(action='ignore', category=FutureWarning)

try:
    import firebase_module
except ImportError:
    class MockFirebase:
        def init_firebase(self): return None
        def create_analysis_session(self, *args): return "local-session"
        def log_visualization_metrics(self, *args): pass
        def log_computation_metrics(self, *args): pass
        def log_plot_performance(self, *args): pass
        def fetch_benchmark_results(self, *args): return pd.DataFrame()
        class PerformanceMonitor:
            def __enter__(self): 
                self.start = time.perf_counter()
                self.duration = 0
                return self
            def __exit__(self, *args): 
                self.duration = time.perf_counter() - self.start
    firebase_module = MockFirebase()

# -----------------------------------------------------------------------------
# UI Customization 
# -----------------------------------------------------------------------------
st.set_page_config(page_title="BioViz Studio", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    /* Global text scaling - Standard readable sizes */
    html, body, [class*="css"], .main, .stMarkdown, p, span, div, label {
        font-size: 16px !important;
        line-height: 1.4 !important;
    }
    
    /* Headers - Balanced hierarchy */
    h1 { font-size: 32px !important; font-weight: 800 !important; margin-bottom: 20px !important; }
    h2 { font-size: 26px !important; font-weight: 700 !important; margin-top: 20px !important; border-bottom: 1px solid #ddd; }
    h3 { font-size: 22px !important; font-weight: 600 !important; }
    
    /* Sidebar Scaling */
    [data-testid="stSidebar"] .stMarkdown p, 
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stRadio div {
        font-size: 14px !important;
    }
    [data-testid="stSidebar"] h1 { font-size: 24px !important; }

    /* Annotation Toolkit and Form Controls */
    .stSelectbox label, .stMultiSelect label, .stNumberInput label, .stTextInput label, .stTextArea label {
        font-size: 14px !important;
        font-weight: bold !important;
        margin-bottom: 5px !important;
    }
    
    /* Input field contents scaling */
    .stSelectbox div[data-baseweb="select"] > div,
    .stMultiSelect div[data-baseweb="select"] > div,
    .stNumberInput input,
    .stTextInput input,
    .stTextArea textarea {
        font-size: 14px !important;
        min-height: 40px !important;
        border-width: 1px !important;
    }
    
    /* Expander Scaling */
    .streamlit-expanderHeader {
        font-size: 16px !important;
        font-weight: bold !important;
        padding: 10px !important;
    }
    
    /* Buttons Scaling */
    .stButton>button {
        font-size: 14px !important;
        height: auto !important;
        padding: 10px 20px !important;
        border-radius: 5px !important;
        font-weight: bold !important;
        width: 100% !important;
    }
    
    /* Metrics Scaling */
    [data-testid="stMetricValue"] {
        font-size: 24px !important;
        font-weight: bold !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 14px !important;
    }
    
    /* Slider Scaling */
    .stSlider label { font-size: 14px !important; font-weight: bold !important; }
    div[data-testid="stThumbValue"] { font-size: 12px !important; }
    
    /* Tab Scaling */
    .stTabs [data-baseweb="tab"] {
        font-size: 14px !important;
        height: 40px !important;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("BioViz Studio: High-Performance Signal Annotation")
st.info(
    "🔒 **Privacy:** uploaded recordings are processed only within this session and are never "
    "uploaded to cloud storage. If optional Firestore logging is enabled, only annotations "
    "(including notes) and performance metrics are stored in your own Firebase project.",
)

@st.cache_data
def load_data(file):
    detected_annotations = []
    try:
        if file.name.lower().endswith('.csv'):
            df = coerce_numeric_columns(pd.read_csv(file, low_memory=False))
            if 'activity_int_merged' in df.columns:
               
                # 4. Sort globally by the new timestamp column
                df = df.sort_values(by='activity_int_merged').reset_index(drop=True)

            return df, None, []
        elif file.name.lower().endswith('.acq'):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.acq') as tmp:
                tmp.write(file.getbuffer())
                tmp_path = tmp.name
            try:
                data = bioread.read_file(tmp_path)
                df = pd.DataFrame()
                df['time'] = data.time_index
                for ch in data.channels:
                    col_name = ch.name if ch.name else f"Channel {ch.frequency}"
                    df[col_name] = ch.data
                return df, int(data.channels[0].samples_per_second), []
            finally:
                if os.path.exists(tmp_path): os.remove(tmp_path)
        elif file.name.lower().endswith('.txt'):
            df = coerce_numeric_columns(pd.read_csv(file, sep=None, engine='python'))
            return df, None, []
        elif file.name.lower().endswith('.zip'):
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = os.path.join(temp_dir, "temp.zip")
                with open(zip_path, "wb") as f:
                    f.write(file.getbuffer())
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                header_files = []
                for root, dirs, files in os.walk(temp_dir):
                    for filename in files:
                        if filename.endswith(".hea"):
                            header_files.append(os.path.join(root, filename))
                if not header_files: return None, None, []
                record_path = header_files[0].replace('.hea', '')
                signals, fields = wfdb.rdsamp(record_path)
                df = pd.DataFrame(signals, columns=fields['sig_name'])
                fs = fields['fs']
                df['time'] = np.arange(len(df)) / fs
                try:
                    if os.path.exists(record_path + '.atr'):
                        ann_obj = wfdb.rdann(record_path, 'atr')
                        for sample_idx, symbol in zip(ann_obj.sample, ann_obj.symbol):
                            t_sec = sample_idx / fs
                            label_map = {'N': 'Normal Beat', 'V': 'PVC', 'A': 'APC', 'L': 'LBBB', 'R': 'RBBB', '+': 'Rhythm Change', '~': 'Artifact'}
                            readable_label = label_map.get(symbol, f"Beat_{symbol}")
                            detected_annotations.append({
                                'id': str(uuid.uuid4()), 'start_time': t_sec, 'end_time': t_sec,
                                'sample_idx': sample_idx, 'label': readable_label, 'type': 'Instantaneous',
                                'notes': f"Native WFDB (Sym: {symbol})"
                            })
                except: pass
                return df, fs, detected_annotations
        return None, None, []
    except Exception as e:
        st.error(f"Error loading file: {e}")
        return None, None, []


def peak_memory_mb():
    """Peak resident memory of this process in MB (0 where unavailable)."""
    if resource is None:
        return 0.0
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is reported in bytes on macOS and in kilobytes on Linux
    return peak / (1024 * 1024) if sys.platform == 'darwin' else peak / 1024


with st.sidebar:
    st.title("Navigation")
    app_mode = st.radio(
        "Select Mode",
        [
            "Analysis Dashboard",
            "Machine Learning (LOPO)",
            "CSV Concatenator (Prep)",
            "Evaluation Experiment"
        ]
    )    
    st.markdown("---")

if app_mode == "CSV Concatenator (Prep)":
    st.header("📂 Preprocessing: Concatenate CSV Files")
    uploaded_files = st.file_uploader("Upload CSV files", type=['csv'], accept_multiple_files=True)
    if uploaded_files:
        if st.button("Concatenate Files", type="primary"):
            st.warning("Concatenation logic placeholder.")

elif app_mode == "Analysis Dashboard":
    if 'custom_labels' not in st.session_state: st.session_state.custom_labels = []

    with st.sidebar:
        st.header("1. Data Input")
        uploaded_file = st.file_uploader("Drag and drop file here", type=['csv', 'zip', 'acq', 'txt'])

    if uploaded_file is not None:
        df, detected_fs, native_anns = load_data(uploaded_file)
        fs_val = detected_fs if detected_fs else 1
        
        if df is not None:
            if 'current_file_id' not in st.session_state or st.session_state.current_file_id != uploaded_file.name:
                session_id = firebase_module.create_analysis_session(uploaded_file.name)
                st.session_state.current_file_id = uploaded_file.name
                st.session_state.firebase_doc_id = session_id
                st.session_state.start_row = 0
                st.session_state.end_row = min(len(df), 5000)
                st.session_state.native_annotations = native_anns
                st.toast(f"✅ Loaded {len(native_anns)} native annotations!", icon="🧬")
            
            current_doc_id = st.session_state.get('firebase_doc_id')

            st.header("Analysis Dashboard")
            st.subheader("1. General Visualization & Annotation")

            x_axis_options = ["Sample Number (Index)"] + list(df.columns)
            # Allow the user to select the X-Axis from this combined list
            x_axis = st.selectbox("Select X-Axis", x_axis_options)

            # Re-derive the 'use_index' boolean to maintain compatibility with the rest of your script
            use_index = (x_axis == "Sample Number (Index)")

            selected_columns = st.multiselect("Select Signals to Visualize", options=df.columns, default=[c for c in df.columns if any(x in c.lower() for x in ['ecg', 'mlii', 'v1'])][:2])

            col_ctrl1, col_ctrl2, col_ctrl3 = st.columns(3)
            with col_ctrl1:
                slice_range = st.slider("Select Range of Samples", 0, len(df), (st.session_state.start_row, st.session_state.end_row), step=100)
                st.session_state.start_row, st.session_state.end_row = slice_range
                btn_prev, btn_next = st.columns(2)
                win = st.session_state.end_row - st.session_state.start_row
                if btn_prev.button("⬅️ Previous Chunk"):
                    st.session_state.start_row = max(0, st.session_state.start_row - win)
                    st.session_state.end_row = st.session_state.start_row + win; st.rerun()
                if btn_next.button("Next Chunk ➡️"):
                    st.session_state.start_row = min(len(df) - win, st.session_state.start_row + win)
                    st.session_state.end_row = st.session_state.start_row + win; st.rerun()
                start_row, end_row = st.session_state.start_row, st.session_state.end_row

            # --- UPDATED: ADDED REMOVE ZEROS AND OUTLIER THRESHOLD ---
            with col_ctrl2: 
                downsample_rate = st.slider("Signal Downsample Rate", 1, 100, 1)
                remove_zeros = st.checkbox("🚫 Remove Zeros", value=False, help="Replaces 0.0 with gaps.")
                # FIX: Added the missing outlier_sigma variable here
                outlier_sigma = st.number_input("Outlier Removal (Sigma)", 0.0, 10.0, 0.0, help="0.0 to disable. Suggest 3.0 for standard cleaning.")

            with col_ctrl3:
                view_mode = st.radio("Display View Mode", ["Overlay", "Stacked"], horizontal=True)
                # Filter columns that contain 'activity' or 'int' for the segment selector
                activity_col_options = [c for c in df.columns if any(x in c.lower() for x in ['activity', 'int', 'label', 'state'])]
                selected_activity_col = st.selectbox("Segment Column (Vertical Lines)", 
                                        options=["None"] + activity_col_options,
                                        help="Select the column to use for generating vertical segment boundaries.")
            # --- Safety valve: warn when the window would send too many points to the browser ---
            MAX_POINTS_PER_TRACE = 5000
            points_per_trace = math.ceil(max(0, end_row - start_row) / max(1, downsample_rate))
            if points_per_trace > MAX_POINTS_PER_TRACE:
                suggested_rate = math.ceil(points_per_trace * downsample_rate / MAX_POINTS_PER_TRACE)
                st.warning(
                    f"⚠️ The selected window contains {points_per_trace:,} points per signal "
                    f"(more than {MAX_POINTS_PER_TRACE:,}). To keep the browser responsive, set the "
                    f"Signal Downsample Rate to {suggested_rate} or narrow the sample range."
                )

            # --- Annotation Management ---
            db_anns = get_annotations(current_doc_id)
            all_current_anns = db_anns + st.session_state.native_annotations + st.session_state.get('stress_test_annotations', [])
            
            with st.sidebar:
                st.header("3. Annotation Filters")
                unique_labels = sorted(list(set([a['label'] for a in all_current_anns])))
                selected_labels = st.multiselect("Toggle Annotation Visibility", options=unique_labels, default=unique_labels)

            with st.expander("📝 Manual Annotation Toolkit", expanded=False):
                st.markdown("#### 📂 Load Custom Event Labels")
                label_file = st.file_uploader("Upload comma-separated labels (.txt)", type=['txt'])
                if label_file:
                    try:
                        content = label_file.getvalue().decode("utf-8")
                        st.session_state.custom_labels = [l.strip() for l in content.split(',') if l.strip()]
                        st.success(f"✅ Loaded {len(st.session_state.custom_labels)} custom labels!")
                    except Exception as e:
                        st.error(f"Error parsing labels: {e}")
                
                st.markdown("---")
                ac1, ac2, ac3, ac4, ac5 = st.columns([1.5, 1, 1, 1.5, 1])
                with ac2: ann_type = st.selectbox("Event Type", ["Interval", "Instantaneous"])
                with ac1:
                    # Base taxonomy; extended at runtime by the uploaded label file.
                    if ann_type == "Interval":
                        default_labels = ["Normal Sinus", "Noise", "Motion Artifact", "Baseline Wander",
                                          "Signal Loss", "Arrhythmia", "Stress Event", "P-wave", "R-wave", "T-wave"]
                    else:
                        default_labels = ["P-wave", "Q-wave", "R-wave", "S-wave", "T-wave", "Other"]
                    combined_labels = list(dict.fromkeys(st.session_state.custom_labels + default_labels))
                    ann_label = st.selectbox("Event Label", combined_labels)
                
                unit_label = "(Samples)" if use_index else "(sec)"
                def_start = start_row if use_index else (start_row / fs_val)
                def_end = end_row if use_index else (end_row / fs_val)
                
                with ac3: ann_start_input = st.number_input(f"Start Point {unit_label}", value=float(def_start))
                with ac4: ann_end_input = st.number_input(f"End Point {unit_label}", value=float(def_end), disabled=(ann_type=="Instantaneous"))
                with ac5: st.write(""); add_btn = st.button("➕ Add Manual Event")
                
                notes = st.text_area("Clinical/Research Notes")
                if add_btn and ann_label:
                    if use_index:
                        ann_start_sec, ann_end_sec = ann_start_input / fs_val, ann_end_input / fs_val
                        s_idx = int(ann_start_input)
                    else:
                        ann_start_sec, ann_end_sec = ann_start_input, ann_end_input
                        s_idx = int(ann_start_input * fs_val)
                    if save_annotation(current_doc_id, ann_start_sec, ann_end_sec if ann_type=="Interval" else ann_start_sec, ann_label, notes, ann_type, sample_idx=s_idx):
                        st.success(f"Added {ann_label}"); time.sleep(0.5); st.rerun()

                if db_anns:
                    df_db_anns = pd.DataFrame(db_anns)
                    st.dataframe(df_db_anns[['label', 'type', 'start_time', 'end_time']], use_container_width=True, height=150)
                    del_id = st.selectbox("Delete Specific Entry", [a['id'] for a in db_anns], format_func=lambda x: f"ID: {x[-6:]}")
                    if st.button("Confirm Delete Entry"): delete_annotation(current_doc_id, del_id); st.rerun()
                
                st.markdown("---")
                st.write("**Dataset Export Options**")
                col_export_1, col_export_2 = st.columns(2)
                with col_export_1:
                    if db_anns:
                        csv_anns = pd.DataFrame(db_anns).to_csv(index=False).encode('utf-8')
                        st.download_button("📥 Download Manual Annotations (CSV)", csv_anns, f"annotations_{current_doc_id}.csv", "text/csv", use_container_width=True)
                with col_export_2:
                    if st.checkbox("Prepare Merged Dataset for ML Training"):
                        with st.spinner("Merging dataset..."):
                            merged_df = merge_annotations(df, db_anns, x_axis, use_index, fs=fs_val)
                            csv_merged = merged_df.to_csv(index=use_index).encode('utf-8')
                            st.download_button("📦 Download Merged Dataset (CSV)", csv_merged, f"merged_{current_doc_id}.csv", "text/csv", type="primary", use_container_width=True)

            # --- PLOTTING LOGIC (NORMALIZED SCALING) ---
            # --- FINAL FIXED PLOTTING LOGIC ---
            if selected_columns:
                with st.spinner("Rendering Signal Visualization..."):
                    with firebase_module.PerformanceMonitor() as pm:
                        df_slice = df.iloc[start_row:end_row:downsample_rate].copy()
                        x_data = df_slice.index if use_index else df_slice[x_axis]

                        # 1. CLEAN DATA & DEFINE SIGNALS
                        # We create 'signals_to_draw' by excluding the activity categorical column
                        signals_to_draw = [c for c in selected_columns if c != selected_activity_col]
                        
                        for col in selected_columns:
                            if not pd.api.types.is_numeric_dtype(df_slice[col]):
                                df_slice[col] = pd.to_numeric(df_slice[col], errors='coerce')
                            if remove_zeros:
                                df_slice[col] = df_slice[col].replace(0, np.nan)
                            if 'outlier_sigma' in locals() and outlier_sigma > 0:
                                series_data = df_slice[col]
                                if not series_data.dropna().empty:
                                    z_scores = np.abs((series_data - series_data.mean()) / series_data.std())
                                    df_slice.loc[z_scores > outlier_sigma, col] = np.nan
                        
                        # 2. INITIALIZE FIGURE (Rows based ONLY on numeric signals)
                        num_rows = len(signals_to_draw) if len(signals_to_draw) > 0 else 1
                        if view_mode == "Stacked":
                            fig = make_subplots(rows=num_rows, cols=1, shared_xaxes=True, vertical_spacing=0.05)
                        else:
                            fig = go.Figure()
                        
                        # 3. DRAW SIGNAL LINES ONLY
                        for i, col in enumerate(signals_to_draw):
                            # EXTRA SAFETY: Do not plot the activity column as a line
                            if col == selected_activity_col:
                                continue
                                
                            trace = go.Scattergl(
                                x=x_data, y=df_slice[col], 
                                mode='lines', name=col, 
                                line=dict(width=3), connectgaps=False
                            )
                            if view_mode == "Stacked":
                                fig.add_trace(trace, row=i+1, col=1)
                            else:
                                fig.add_trace(trace)

                        # 4. DRAW ACTIVITY SEGMENTS (Green/Red Lines)
     # 4. DRAW ACTIVITY SEGMENTS (Green/Red Lines with Academic-Level Fonts)
                        if selected_activity_col != "None" and selected_activity_col in df_slice.columns:
                            act_data = df_slice[selected_activity_col].values
                            changes = np.where(act_data[:-1] != act_data[1:])[0]
                            boundary_indices = np.unique(np.concatenate(([0], changes, [len(act_data)-1])))
                            
                            for idx in range(len(boundary_indices) - 1):
                                start_pos = boundary_indices[idx]
                                end_pos = boundary_indices[idx+1]
                                label_val = act_data[start_pos + 1] if start_pos + 1 < len(act_data) else act_data[start_pos]
                                
                                if pd.isna(label_val) or label_val == -1: 
                                    continue
                                
                                x_s = x_data[start_pos] if use_index else x_data.iloc[start_pos]
                                x_e = x_data[end_pos] if use_index else x_data.iloc[end_pos]
                                
                                # Calculate Precise Midpoint for Centering
                                x_center = x_s + (x_e - x_s) / 2
                                
                                # Start boundary (Green Dash)
                                fig.add_vline(x=x_s, line_width=2.5, line_dash="dash", line_color="green", opacity=0.8, row="all" if view_mode == "Stacked" else None)
                                # End boundary (Red Dot)
                                fig.add_vline(x=x_e, line_width=2.5, line_dash="dot", line_color="red", opacity=0.8, row="all" if view_mode == "Stacked" else None)
                                
                                # Centered Categorical Label (Paper Font Size: 28)
                                fig.add_annotation(
                                    x=x_center, 
                                    y=1.02, 
                                    yref="paper",
                                    text=f"<b>{label_val}</b>",
                                    showarrow=False, 
                                    font=dict(color="black", size=28, family="Arial"), 
                                    bgcolor="rgba(0,0,0,0)" 
                                )

                        # 5. DRAW ANNOTATIONS
                        # Instantaneous events: dashed vertical line + marker; interval events:
                        # semi-transparent band. Visibility follows the sidebar label filter.
                        plot_anns = [a for a in all_current_anns if a['label'] in selected_labels]
                        px_colors = px.colors.qualitative.Alphabet
                        color_map = {lbl: px_colors[idx % len(px_colors)] for idx, lbl in enumerate(selected_labels)}

                        for lbl in selected_labels:
                            fig.add_trace(go.Scatter(
                                x=[None], y=[None], mode='markers',
                                marker=dict(color=color_map[lbl], size=12, symbol='square'),
                                name=f"<b>{lbl}</b>", showlegend=True
                            ))

                        for ann in plot_anns:
                            s_idx = ann.get('sample_idx')
                            if s_idx is None:
                                s_idx = int(ann['start_time'] * fs_val)
                            e_idx = int(ann['end_time'] * fs_val) if ann.get('type') == 'Interval' else s_idx
                            if max(s_idx, start_row) <= min(e_idx, end_row):
                                x_pos = s_idx if use_index else (s_idx / fs_val)
                                color = color_map.get(ann['label'], "gray")
                                if ann.get('type') == 'Instantaneous':
                                    fig.add_vline(x=x_pos, line_width=1, line_dash="dash", line_color=color, opacity=0.9)
                                    try: y_max = df_slice[signals_to_draw[0]].max()
                                    except: y_max = 0
                                    fig.add_trace(go.Scattergl(
                                        x=[x_pos], y=[y_max], mode='markers',
                                        marker=dict(color=color, size=10, symbol='diamond-tall'),
                                        hoverinfo='text', text=f"{ann['label']}",
                                        showlegend=False
                                    ))
                                else:
                                    x_end = e_idx if use_index else (e_idx / fs_val)
                                    fig.add_vrect(x0=x_pos, x1=x_end, fillcolor=color, opacity=0.3, layer="below", line_width=0, row="all" if view_mode == "Stacked" else None)

                        # 6. LAYOUT & AXIS TITLES (Optimized for Double-Column Papers)
                        dynamic_x_title = "<b>Samples (N)</b>" if use_index else f"<b>{x_axis}</b>"
                        medical_keywords = ['ecg', 'mlii', 'v1', 'eda', 'ppg']
                        is_medical = any(any(k in col.lower() for k in medical_keywords) for col in signals_to_draw)
                        dynamic_y_title = "<b>Amplitude (mV)</b>" if is_medical else "<b>Magnitude</b>"

                        fig.update_layout(
                            height=450 * len(signals_to_draw) if view_mode == "Stacked" else 700, 
                            template="plotly_white", 
                            legend=dict(
                                orientation="h", yanchor="bottom", y=1.08, xanchor="center", x=0.5,
                                font=dict(size=26) # Large Legend Font
                            ),
                            xaxis_title=dict(text=dynamic_x_title, font=dict(size=32)), # Academic Title Size
                            margin=dict(t=120, b=120, l=120, r=40)
                        )

                        # Update Font for All Ticks and Subplot Y-Axes
                        fig.update_xaxes(tickfont=dict(size=36), title_font=dict(size=32))
                        fig.update_yaxes(tickfont=dict(size=36), title_font=dict(size=32))

                        if view_mode == "Stacked":
                            for i in range(len(signals_to_draw)): 
                                fig.update_yaxes(title_text=dynamic_y_title, row=i+1, col=1)
                        else:
                            fig.update_yaxes(title_text=dynamic_y_title)
                        st.plotly_chart(fig, use_container_width=True)
                    st.caption(f"⚡ Performance Metrics | Plot Generation: {pm.duration*1000:.2f} ms")
                    firebase_module.log_plot_performance(
                        current_doc_id, uploaded_file.name, pm.duration * 1000,
                        len(df_slice) * len(signals_to_draw), len(signals_to_draw))

            st.markdown("---")
            st.subheader("2. Advanced ECG Analysis")
            with st.expander("ECG Algorithm Settings"):
                tgt = st.selectbox("Select Target ECG Lead", [c for c in df.columns if any(x in c.lower() for x in ['ecg', 'mlii', 'v1'])] or df.columns)
                if st.button("Execute Peak Detection"):
                    peaks, hr, _, clean = process_ecg(df[tgt].iloc[start_row:end_row], fs_val)
                    f1 = go.Figure()
                    f1.add_trace(go.Scattergl(y=clean, name='Processed Lead', line_color='gray', line=dict(width=1.5)))
                    f1.add_trace(go.Scattergl(x=peaks, y=clean[peaks], mode='markers', name='Detected R-Peaks', marker=dict(color='red', size=8, symbol='x')))
                    f1.update_layout(
                        template="plotly_white", 
                        font=dict(size=12),
                        xaxis_title=dict(text="<b>Sample Index</b>", font=dict(size=14)),
                        yaxis_title=dict(text="<b>Voltage (mV)</b>", font=dict(size=14)),
                        margin=dict(t=50, b=50, l=50, r=40)
                    )
                    st.plotly_chart(f1, use_container_width=True)
# -----------------------------------------------------------------------------
# MACHINE LEARNING (LOPO)
# -----------------------------------------------------------------------------
elif app_mode == "Machine Learning (LOPO)":

    st.title("🤖 Machine Learning – Leave-One-Participant-Out")

    st.info("""
    Upload a feature table (e.g., PSD features).

    Required columns:
    - participantId
    - BehaviorCode
    """)

    uploaded_file = st.file_uploader(
        "Drag & Drop Feature CSV Here",
        type=["csv"]
    )

    if uploaded_file:

        df_raw = pd.read_csv(uploaded_file)

        st.success(f"Loaded: {uploaded_file.name}")
        st.write("Shape:", df_raw.shape)

        # ------------------------------
        # Validate Required Columns
        # ------------------------------
        required_cols = ["participantId", "BehaviorCode"]

        if not all(col in df_raw.columns for col in required_cols):
            st.error("Missing required columns: participantId or BehaviorCode")
            st.stop()

        # Binary label enforcement
        df_raw["type"] = df_raw["BehaviorCode"]
        df_raw = df_raw[df_raw["type"].isin([0, 1])]

        st.write("Class Distribution:")
        st.write(df_raw["type"].value_counts())

        # ------------------------------
        # Model Selection
        # ------------------------------
        model_choice = st.selectbox(
            "Select ML Model",
            [
                "Random Forest",
                "Support Vector Machine",
                "Decision Tree",
                "Gradient Boosting"
            ]
        )

        undersample_choice = st.selectbox(
            "Undersampling Method",
            ["Rus", "Clus", "None"]
        )

        if st.button("🚀 Run LOPO Training"):

            with firebase_module.PerformanceMonitor() as pm:

                start_time = time.time()

                if model_choice == "Random Forest":
                    results_df, summary = rf_leave_one_participant_out_weighted(
                        df_raw,
                        undersample_method=undersample_choice,
                        save_dir=None
                    )

                elif model_choice == "Support Vector Machine":
                    results_df, summary = svm_leave_one_participant_out_weighted(
                        df_raw,
                        undersample_method=undersample_choice,
                        save_dir=None
                    )

                elif model_choice == "Decision Tree":
                    results_df, summary = dt_leave_one_participant_out(
                        df_raw,
                        undersample_method=undersample_choice,
                        save_dir=None
                    )

                elif model_choice == "Gradient Boosting":
                    results_df, summary = gb_leave_one_participant_out(
                        df_raw,
                        undersample_method=undersample_choice,
                        save_dir=None
                    )

                end_time = time.time()

            duration_sec = end_time - start_time

            st.success("Training Completed!")

            st.subheader("📊 Fold-Level Results")
            st.dataframe(results_df, use_container_width=True)

            st.subheader("📈 Summary Metrics")
            st.json(summary)

            st.download_button(
                "Download Fold Results CSV",
                results_df.to_csv(index=False),
                file_name=f"{model_choice}_LOPO_results.csv"
            )

            st.download_button(
                "Download Summary JSON",
                json.dumps(summary, indent=4),
                file_name=f"{model_choice}_LOPO_summary.json"
            )

            st.caption(f"⚡ Total Training Time: {duration_sec:.2f} seconds")
# -----------------------------------------------------------------------------
# Evaluation Benchmarking
# -----------------------------------------------------------------------------
elif app_mode == "Evaluation Experiment":
    st.header("🧪 Experiment: Visualization Latency Benchmark")
    source_type = st.radio("Experiment Data Source", ["Local Path", "File Upload"], horizontal=True)
    dataset_path = None
    
    if source_type == "Local Path":
        dataset_path = st.text_input("Directory Path", placeholder="/path/to/dataset").strip()
    else: 
        uploaded_files = st.file_uploader("Upload Benchmark Files (CSV or WFDB Pairs)", accept_multiple_files=True)
        if uploaded_files:
            if 'eval_temp_dir' not in st.session_state: st.session_state.eval_temp_dir = tempfile.mkdtemp()
            for uf in uploaded_files:
                save_path = os.path.join(st.session_state.eval_temp_dir, uf.name)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f: f.write(uf.getbuffer())
            dataset_path = st.session_state.eval_temp_dir

    if dataset_path and os.path.exists(dataset_path):
        if 'eval_files' not in st.session_state: st.session_state.eval_files = []
        if st.button("Scan Dataset Directory"):
            found = []
            for root, dirs, files in os.walk(dataset_path):
                for f in files:
                    if f.endswith('.hea'):
                        rec_name = f.replace('.hea', '')
                        rec_path = os.path.join(root, rec_name)
                        try:
                            h = wfdb.rdheader(rec_path)
                            found.append({
                                'file': rec_name, 'path': rec_path, 'type': 'WFDB',
                                'duration_min': (h.sig_len/h.fs)/60 if h.fs else 0, 
                                'samples': h.sig_len, 'n_sig': h.n_sig
                            })
                        except: pass
                    elif f.endswith('.csv'):
                        try:
                            f_path = os.path.join(root, f)
                            df_tmp = pd.read_csv(f_path, nrows=2)
                            found.append({
                                'file': f, 'path': f_path, 'type': 'CSV',
                                'duration_min': 0, 'samples': 0, 'n_sig': len(df_tmp.columns)
                            })
                        except: pass
            st.session_state.eval_files = found
            st.success(f"Discovered {len(found)} valid signal records.")

        if st.session_state.eval_files:
            st.subheader("⚙️ Benchmark Configuration")
            with st.expander("📂 Filter Record List", expanded=True):
                filter_term = st.text_input("Substring Filter (Case-Insensitive)", "")
                filtered_files = [f for f in st.session_state.eval_files if filter_term.lower() in f['file'].lower()]
                st.write(f"**Selection Status:** {len(filtered_files)} records queued.")

            c1, c2, c3 = st.columns(3)
            with c1: n_trials = st.number_input("Number of Trials", 1, 20, 5)
            with c2: n_ch = st.number_input("Channels to Process", 1, 20, 1)
            with c3: max_p = st.number_input("Max Point Limit (0=All)", 0, 1000000, 0)

            if st.button("🚀 Execute Latency Benchmark"):
                if not filtered_files:
                    st.error("No records matched the filter criteria.")
                else:
                    sid = firebase_module.create_analysis_session("BENCHMARK", "evaluation_experiment")
                    local_results = []  # kept locally so results are available without Firebase
                    pb = st.progress(0); status = st.empty()
                    total_ops = len(filtered_files) * n_trials; curr_op = 0
                    
                    for f_info in filtered_files:
                        try:
                            status.write(f"Loading Record: {f_info['file']}...")
                            t_load_start = time.perf_counter()
                            if f_info['type'] == 'WFDB':
                                record, _ = wfdb.rdsamp(f_info['path'])
                                data_block = record
                            else:
                                df_bench = pd.read_csv(f_info['path'], engine='c', low_memory=False)
                                data_block = df_bench.select_dtypes(include=[np.number]).values
                                del df_bench; gc.collect()
                            t_load = time.perf_counter() - t_load_start
                            
                            for t in range(n_trials):
                                status.write(f"Trial {t+1}/{n_trials} for {f_info['file']}")
                                t1 = time.perf_counter()
                                fig = go.Figure()
                                end_idx = max_p if (max_p > 0 and max_p < len(data_block)) else len(data_block)
                                actual_ch = min(n_ch, data_block.shape[1])
                                for ch_idx in range(actual_ch):
                                    fig.add_trace(go.Scatter(y=data_block[:end_idx, ch_idx], mode='lines'))
                                
                                t_plot = time.perf_counter() - t1
                                total_p = end_idx * actual_ch
                                
                                peak_mb = peak_memory_mb()
                                firebase_module.log_computation_metrics(sid, f_info['file'], f"bench_{f_info['type']}", t_load + t_plot, peak_mb, (total_p / (t_load + t_plot)) / 1000)
                                firebase_module.log_plot_performance(sid, f_info['file'], t_plot * 1000, total_p, actual_ch)
                                local_results.append({
                                    'file_name': f_info['file'],
                                    'analysis_type': f"bench_{f_info['type']}",
                                    'trial': t + 1,
                                    'execution_time_ms': (t_load + t_plot) * 1000,
                                    'peak_memory_mb': peak_mb,
                                    'throughput_ksps': (total_p / (t_load + t_plot)) / 1000,
                                    'plot_gen_time_ms': t_plot * 1000,
                                    'total_points_rendered': total_p,
                                    'active_trace_count': actual_ch,
                                })
                                curr_op += 1; pb.progress(curr_op / total_ops)
                            
                            del data_block; gc.collect()
                        except Exception as e:
                            st.error(f"Execution Error on {f_info['file']}: {str(e)}")
                            curr_op += n_trials; pb.progress(min(1.0, curr_op / total_ops))
                    
                    st.success("Experimental Benchmark Complete!"); st.balloons()
                    with st.spinner("Compiling Results CSV..."):
                        df_results = firebase_module.fetch_benchmark_results(sid) if sid else None
                        if df_results is None or df_results.empty:
                            df_results = pd.DataFrame(local_results)
                        if not df_results.empty:
                            st.download_button("📥 Download Latency Results (CSV)", df_results.to_csv(index=False).encode('utf-8'), f"benchmark_{sid or 'local'}.csv", "text/csv", type="primary")