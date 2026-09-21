# Benchmark result files

`eval_benchmark.ipynb` expects the CSVs exported by the app's **Evaluation Experiment** mode
in this folder, with this layout:

```text
eval_data/
├── MIT_BIH_Stress_Noise_Trace1.csv
├── MIT_BIH_LongTermData/
│   ├── trace1_MITBIH_LongTerm_benchmark_results_EVAL_BATCH_tmp57v9l9qd_20260120_171527_21ba.csv
│   └── trace2_MITBIH_LongTerm_benchmark_results_EVAL_BATCH_tmp57v9l9qd_20260120_171643_0cb4.csv
├── MIT_BIH_Stress_Noise_Trace2_LocalDesktop/
│   ├── MIT_BIH_Stress_Trace1_LocalDesktop.csv
│   └── MIT_BIH_Stress_Trace2_LocalDesktop.csv
├── MIT_BIH_Stress_Noise_Trace2_LocalDesktop_Container/
│   ├── MIT_BIH_Stress_Noise_Trace1.csv
│   └── MITBIH_Stress_Noise_Trace2.csv
└── MindGame/
    ├── MindGame_ACC_GYRO_Trace_1.csv
    ├── MindGame_ACC_GYRO_Trace_2.csv
    ├── MindGame_ACC_GYRO_Trace_3.csv
    └── MindGame_HR_Trace_1.csv
```

To regenerate them, download the PhysioNet databases (`python ../download_physionet.py`),
run the app, open **Evaluation Experiment**, point it at the downloaded folder, and export
the results CSV for 1, 2 (and, for the wearable data, 3) channels with 5 trials each.

## Status in this repository

Included: all files above except the four *local vs. container* comparison files
(`MIT_BIH_Stress_Noise_Trace2_LocalDesktop/*` and `MIT_BIH_Stress_Noise_Trace2_LocalDesktop_Container/*`).
Those were recorded on an external drive and still need to be added so the
"Local vs Container" section of the notebook (paper Fig. 6) can run.
