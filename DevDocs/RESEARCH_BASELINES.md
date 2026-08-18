# Research baseline notes

## 1. Upstream protocol

The associated paper frames welding defect detection as anomaly detection rather than 12-way classification.

The important experimental rule is:

- Fit on Good samples in the training partition only.
- Tune on validation.
- Report once on test.

The paper's learned approaches include an audio convolutional autoencoder, fixed video features followed by an autoencoder, and standardized late fusion. The starter repository does not claim to reproduce those results.

## 2. Included baseline

`weldtool features` creates a table of bounded, handcrafted features. `weldtool baseline` then fits an Isolation Forest to Good training rows.

This baseline is useful for:

- Verifying labels and split semantics.
- Finding gross modality corruption or highly separable acquisition artifacts.
- Exercising score generation and category-wise AUC reporting.
- Establishing a deterministic smoke-test pipeline.

It is not a scientific comparison to the paper's video/audio neural models.

## 3. Leakage controls

Before interpreting any metric:

- Confirm train contains no defect categories.
- Audit whether a physical session crosses splits.
- Check duplicate and near-duplicate recordings.
- Avoid selecting preprocessing parameters using test performance.
- Fit imputation, scaling, score standardization, and thresholds on train/validation only.
- Group bootstrap confidence intervals by acquisition session, not individual sample, when correlations are material.

## 4. Labels

The public documentation warns that labels represent intended defect generation and were not verified post-weld by an expert. A weld may contain multiple defects.

Consequences:

- Treat category-specific metrics as noisy conditional analyses.
- Preserve `category_raw` and normalized category separately.
- Do not interpret a low category AUC as definitive physical unobservability without label audit.
- Consider robust or positive-unlabeled methods for later work.

## 5. Suggested staged experiments

### Stage A — data truth

- Reproduce exact upstream counts and split composition.
- Plot duration, FPS, sample-rate, image-resolution, and sensor-schema distributions.
- Establish modality missingness/corruption rates.
- Audit acquisition-session leakage.

### Stage B — simple unimodal baselines

- Sensor: robust statistics + Isolation Forest / one-class SVM.
- Audio: log-STFT summary + shallow autoencoder.
- Video: frozen modern video embedding + feature autoencoder.
- Post-weld images: frozen image embedding + nearest-neighbor anomaly score.

### Stage C — learned temporal models

- Audio windows with explicit latency and sample-rate policy.
- Video clips with exact temporal sampling and smoothing policy.
- Sensor temporal encoder with a documented time base.

### Stage D — fusion

- Standardize scores using Good training data.
- Tune convex weights on validation only.
- Compare fixed, learned, and reliability-aware fusion.
- Report all unimodal and fused operating points, not only aggregate AUC.

## 6. Metrics

Recommended minimum:

- ROC AUC overall and by defect category.
- Precision-recall AUC under a realistic defect prevalence sensitivity analysis.
- Equal-error rate.
- False-negative rate at fixed false-positive rates.
- Threshold drift across weld type, material, thickness, and session.
- Bootstrap confidence intervals grouped by session.
- Latency and memory for windowed online inference.
