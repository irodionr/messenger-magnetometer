# %% imports

import os
import random
import sys
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import tensorflow as tf
from sklearn.metrics import (accuracy_score, confusion_matrix,
                             precision_recall_fscore_support)
from sklearn.utils.class_weight import compute_class_weight
from tensorflow import keras
from tensorflow.keras import layers

from util import load_data, load_drifts, print_f, select_features

global fptr


# %% Functions

# Wrapper for print function
def print_(print_str, with_date=True):

    global fptr
    print_f(fptr, print_str, with_date)


# Create CNN model
def cnn(shape):
    model = keras.Sequential()
    model.add(layers.Conv1D(64, 3, activation='relu', input_shape=shape))
    model.add(layers.Dense(16, activation='relu'))
    model.add(layers.MaxPooling1D())
    model.add(layers.Flatten())
    model.add(layers.Dense(5, activation='softmax'))

    model.compile(loss=keras.losses.SparseCategoricalCrossentropy(),
                  optimizer='adam', metrics=['accuracy'])

    return model


# Train classifier based on drift
def train_clf(df, max_count=5):

    # Standardization
    df_features = df.iloc[:, 1:-4]
    print_(f'features:\n{df_features.head()}')
    print_(f'mean:\n{df_features.mean()}')
    print_(f'std:\n{df_features.std()}')

    df.iloc[:, 1:-4] = (df_features - df_features.mean()) / df_features.std()
    print_(f'standardized:\n{df.iloc[:, 1:-4].head()}')
    print_(f'mean:\n{df.iloc[:, 1:-4].mean()}')
    print_(f'std:\n{df.iloc[:, 1:-4].std()}')
    print_(f'total size = {len(df.index)}')

    clf = cnn((len(df_features.columns), 1))
    print_('cnn:')
    clf.summary(print_fn=print_)

    drifts = pd.unique(df['DRIFT']).tolist()
    print_(f'drifts: {drifts}')

    for drift in drifts:

        df_drift = df.loc[df['DRIFT'] == drift]
        orbit_numbers = pd.unique(df_drift['ORBIT']).tolist()
        print_(f'{len(orbit_numbers)} train orbits with drift {drift}')
        if len(orbit_numbers) > max_count:
            random.shuffle(orbit_numbers)
            orbit_numbers = orbit_numbers[:max_count]
        print_(f'selected orbits for training: {orbit_numbers}')

        for orbit in orbit_numbers:

            df_orbit = df_drift.loc[df['ORBIT'] == orbit]
            features = df_orbit.iloc[:, 1:-4].values
            labels = df_orbit['LABEL'].tolist()
            classes = np.unique(labels)
            weights = compute_class_weight(
                'balanced', classes=classes, y=labels)

            x = np.array(features, copy=True)
            x = x.reshape(-1, x.shape[1], 1)
            y = np.asarray(labels)

            print_(f'training classifier on orbit {orbit}')
            clf.fit(x=x, y=y,
                    batch_size=64,
                    epochs=20,
                    class_weight={k: v for k,
                                  v in enumerate(weights)},
                    verbose=0)

    print_('cnn:')
    clf.summary(print_fn=print_)

    return clf


# Test classifier
def test_clfs(df, clf):

    df['LABEL_PRED'] = 0

    # Standardization
    df_features = df.iloc[:, 1:-5]
    print_(f'features:\n{df_features.head()}')
    print_(f'mean:\n{df_features.mean()}')
    print_(f'std:\n{df_features.std()}')

    df.iloc[:, 1:-5] = (df_features - df_features.mean()) / df_features.std()
    print_(f'standardized:\n{df.iloc[:, 1:-5].head()}')
    print_(f'mean:\n{df.iloc[:, 1:-5].mean()}')
    print_(f'std:\n{df.iloc[:, 1:-5].std()}')
    print_(f'total size = {len(df.index)}')

    orbit_numbers = pd.unique(df['ORBIT']).tolist()
    for orbit in orbit_numbers:

        df_orbit = df.loc[df['ORBIT'] == orbit]
        features = df_orbit.iloc[:, 1:-5].values

        x = np.array(features, copy=True)
        x = x.reshape(-1, x.shape[1], 1)

        print_(
            f'testing classifier on orbit {orbit} ({df_orbit.iloc[0]["SPLIT"]})')
        pred = clf.predict(x)  # window vs step
        labels = df['LABEL']
        labels_pred = pred.argmax(axis=-1)
        df.loc[df['ORBIT'] == orbit, 'LABEL_PRED'] = labels_pred

        f1 = precision_recall_fscore_support(
            y_true=labels, y_pred=labels_pred, average=None, labels=np.unique(labels))[2]
        print(f'f-score: {f1}')

    return df['LABEL_PRED']


# Plot all orbits with crossings
def plot_orbits(logs, df, test=False, pred=False, draw=[1, 3]):

    colours = {0: 'red', 1: 'green', 2: 'yellow', 3: 'blue', 4: 'purple'}
    title = 'labels in training orbit '
    folder = 'train-'
    if test:
        title = 'labels in testing orbit '
        folder = 'test-'
        df = df.loc[df['SPLIT'] == 'test']
    else:
        df = df.loc[df['SPLIT'] == 'train']

    label_col = 'LABEL'
    if pred:
        label_col = 'LABEL_PRED'
        title = 'Preicted ' + title
        folder += 'pred'
    else:
        title = 'True ' + title
        folder += 'true'

    if not os.path.exists(f'{logs}/{folder}'):
        os.makedirs(f'{logs}/{folder}')

    for orbit in pd.unique(df['ORBIT']).tolist():

        df_orbit = df.loc[df['ORBIT'] == orbit]
        fig = go.Figure()

        # Plotting components of the magnetic field B_x, B_y, B_z in MSO coordinates
        fig.add_trace(go.Scatter(
            x=df_orbit['DATE'], y=df_orbit['BX_MSO'], name='B_x'))
        fig.add_trace(go.Scatter(
            x=df_orbit['DATE'], y=df_orbit['BY_MSO'], name='B_y'))
        fig.add_trace(go.Scatter(
            x=df_orbit['DATE'], y=df_orbit['BZ_MSO'], name='B_z'))

        # Plotting total magnetic field magnitude B along the orbit
        fig.add_trace(go.Scatter(
            x=df_orbit['DATE'], y=-df_orbit['B_tot'], name='|B|', line_color='darkgray'))
        fig.add_trace(go.Scatter(x=df_orbit['DATE'], y=df_orbit['B_tot'], name='|B|',
                                 line_color='darkgray', showlegend=False))

        for i in draw:
            for _, row in df_orbit.loc[df_orbit[label_col] == i].iterrows():
                fig.add_trace(go.Scatter(
                    x=[row['DATE'], row['DATE']],
                    y=[-450, 450],
                    mode='lines',
                    line_color=colours[i],
                    opacity=0.1,
                    showlegend=False
                ))

        fig.update_layout(
            {'title': f'{title}{orbit} (drift {df_orbit.iloc[0]["DRIFT"]})'})
        fig.write_image(
            f'{logs}/{folder}/fig{orbit}_drift{df_orbit.iloc[0]["DRIFT"]}.png')
        # fig.write_html(
        #     f'{logs}/{folder}/fig_{orbit}.png')


# %% Setup

gpus = tf.config.list_physical_devices('GPU')
if gpus:
    try:
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)
    except RuntimeError as e:
        print_(e)

logs = sys.argv[1]
dataset = int(sys.argv[2])
plots = sys.argv[3]
if not os.path.exists(logs):
    os.makedirs(logs)

fptr = open(f'{logs}/log_cnn.txt', 'w')
print_(f'dataset: {dataset}')


# %% Load data

drift_orbits = load_drifts(f'data/drifts_set{dataset}.txt')
files = []
cur_orbit = 0
for orb in drift_orbits:
    if cur_orbit < 100:
        files.append(f'data/drifts/df_{orb}.csv')
        print_(f'data/drifts/df_{orb}.csv', with_date=False)
    else:
        files.append(f'data/orbits/df_{orb}.csv')
        print_(f'data/orbits/df_{orb}.csv', with_date=False)
    cur_orbit += 1

df = load_data(files)
df = select_features(df, 'data/features_cnn.txt')
df['DRIFT'] = 1
df['SPLIT'] = 'train'

# Randomly select orbits for testing
len_train = 0
len_test = 0
for drift in np.unique(list(drift_orbits.values())):

    all_orbits = [k for k, v in drift_orbits.items() if v == drift]
    test_count = len(all_orbits) // 5
    if test_count == 0:
        test_count = 1

    test_orbits = random.sample(all_orbits, test_count)
    train_orbits = [orb for orb in all_orbits if orb not in test_orbits]
    len_train += len(train_orbits)
    len_test += len(test_orbits)

    print_(f'train orbits for drift {drift}: {train_orbits}')
    for orb in train_orbits:
        df.loc[df['ORBIT'] == orb, 'DRIFT'] = drift
    print_(f'test orbits for drift {drift}: {test_orbits}')
    for orb in test_orbits:
        df.loc[df['ORBIT'] == orb, 'DRIFT'] = drift
        df.loc[df['ORBIT'] == orb, 'SPLIT'] = 'test'

print_(f'selected data:\n{df.head()}')
print_(f'total train orbits: {len_train}')
print_(f'total test orbits: {len_test}')


# %% Training classifiers

t1 = time.perf_counter()
clf = train_clf(df.loc[df['SPLIT'] == 'train'].copy())
t2 = time.perf_counter()
print_(f'training time is {t2 - t1:.2f} seconds')


# %% Testing classifiers

t1 = time.perf_counter()
df_pred = test_clfs(df.copy(), clf)
t2 = time.perf_counter()
print_(f'testing time is {t2 - t1:.2f} seconds')

df = df.join(df_pred)


# %% Evaluation

labels_train_true = df.loc[df['SPLIT'] == 'train', 'LABEL'].tolist()
labels_train_pred = df.loc[df['SPLIT'] == 'train', 'LABEL_PRED'].tolist()
labels_test_true = df.loc[df['SPLIT'] == 'test', 'LABEL'].tolist()
labels_test_pred = df.loc[df['SPLIT'] == 'test', 'LABEL_PRED'].tolist()

auc_value = accuracy_score(y_true=labels_train_true, y_pred=labels_train_pred)
print_(f'accuracy value is {auc_value} for training dataset')
prf = precision_recall_fscore_support(
    labels_train_true, labels_train_pred, average=None, labels=np.unique(labels_train_true))
print_(f'precision: {prf[0]}')
print_(f'recall: {prf[1]}')
print_(f'f-score: {prf[2]}')
print_(f'support: {prf[3]}')
print_(
    f'confusion matrix:\n{confusion_matrix(labels_train_true, labels_train_pred)}')

auc_value = accuracy_score(y_true=labels_test_true, y_pred=labels_test_pred)
print_(f'accuracy value is {auc_value} for testing dataset')
prf = precision_recall_fscore_support(
    labels_test_true, labels_test_pred, average=None, labels=np.unique(labels_test_true))
print_(f'precision: {prf[0]}')
print_(f'recall: {prf[1]}')
print_(f'f-score: {prf[2]}')
print_(f'support: {prf[3]}')
print_(
    f'confusion matrix:\n{confusion_matrix(labels_test_true, labels_test_pred)}')


# %% Plots

df['B_tot'] = (df['BX_MSO']**2 + df['BY_MSO']**2 + df['BZ_MSO']**2)**0.5
if plots != '':
    print_(f'plotting {plots}...')
    if '0' in plots:
        plot_orbits(logs, df, test=False, pred=False)
        print_(f'plotted train-true')
    if '1' in plots:
        plot_orbits(logs, df, test=False, pred=True)
        print_(f'plotted train-pred')
    if '2' in plots:
        plot_orbits(logs, df, test=True, pred=False)
        print_(f'plotted test-true')
    if '3' in plots:
        plot_orbits(logs, df, test=True, pred=True)
        print_(f'plotted test-pred')


# %% Close log file

if fptr is not None:
    fptr.close()
    fptr = None
