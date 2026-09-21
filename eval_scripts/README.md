# Reproducing the paper's benchmarks

1. **Get the signals.** Download the two PhysioNet databases:

   ```bash
   pip install wfdb
   python download_physionet.py
   ```

   The wearable behavioral dataset is described in Sadhu et al., *IoT 2025*
   (doi:10.1145/3770501.3770523).

2. **Run the benchmark.** Start the app (`docker compose up --build` from the repository root),
   choose **Evaluation Experiment**, enter the data folder, click **Scan Dataset Directory**,
   set *Number of Trials* = 5 and *Channels to Process* = 1 or 2, then **Execute Latency Benchmark**
   and download the results CSV. Results are recorded locally; Firebase is not required.

3. **Plot the results.** Put the CSVs in `eval_data/` (layout in `eval_data/README.md`) and open
   `eval_benchmark.ipynb`, either locally or in the bundled Jupyter container:

   ```bash
   docker compose up --build      # from this folder; opens JupyterLab on http://localhost:8888
   ```

Latency is measured with `time.perf_counter()` as load time (disk to NumPy) plus figure-construction
time; throughput is samples × channels divided by total latency, reported in kilo-samples per second.
