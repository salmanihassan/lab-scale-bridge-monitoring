%% Temperature Drift Analysis
%
% Files:
%
%   accelerometer_vib_tempvariation_821.xlsx
%       Col 1 = X accel
%       Col 2 = Y accel
%       Col 3 = Z accel
%       Col 4 = Temperature (deg C)
%
%   load_cell_temperature_cleaned.xlsx
%       Col 1 = Temperature (deg C)
%       Col 2 = Load cell raw output
%
% Purpose:
%   Examine sensor output drift as the heated beam cools from
%   approximately 60 deg C toward room temperature.
%
%   Large transient spikes in the accelerometer data are treated as
%   anomalies and interpolated before calculating thermal drift.

clear;
clc;
close all;


%% ================================================================
%  USER SETTINGS
% =================================================================

% Time between recorded samples
accelSamplePeriod_s = 1;     % seconds/sample
loadSamplePeriod_s  = 1;     % seconds/sample

% Smoothing windows
accelSmoothWindow = 250;     % samples
loadSmoothWindow  = 15;      % samples

% Accelerometer anomaly detection
%
% These spikes are much larger than the actual slow thermal drift, so a
% robust median-based outlier detector works well here.
accelOutlierThreshold = 6;

% Temperature anomaly detection
tempOutlierWindow    = 101;  % samples
tempOutlierThreshold = 5;

% Physical temperature limits used as a sanity check
minValidTemp = 0;
maxValidTemp = 100;


%% ================================================================
%  PLOT 1 - ACCELEROMETER TEMPERATURE DRIFT
% =================================================================

%% Load accelerometer data

accelData = readmatrix('accelerometer_vib_tempvariation_821.xlsx');

% Only use first four columns
accelData = accelData(:,1:4);

% Remove rows containing missing/non-finite values
accelData = accelData(all(isfinite(accelData),2),:);

X = accelData(:,1);
Y = accelData(:,2);
Z = accelData(:,3);
T_accel = accelData(:,4);


%% ---------------------------------------------------------------
%  Clean temperature data FIRST
% ----------------------------------------------------------------

% Reject physically unrealistic temperature measurements
badTemp = ...
    T_accel < minValidTemp | ...
    T_accel > maxValidTemp;

T_accel(badTemp) = NaN;

% Interpolate across obviously invalid temperature points
T_accel = fillmissing( ...
    T_accel, ...
    'linear', ...
    'EndValues','nearest');


% Remove isolated temperature spikes using a moving median
T_accel_clean = filloutliers( ...
    T_accel, ...
    'linear', ...
    'movmedian', ...
    tempOutlierWindow, ...
    'ThresholdFactor',tempOutlierThreshold);


%% ---------------------------------------------------------------
%  Find beginning of cooldown
% ----------------------------------------------------------------

% Light smoothing is only used to locate the peak temperature robustly
T_startDetect = movmean(T_accel_clean,31);

% Locate maximum valid temperature
[~,startIdx] = max(T_startDetect);


% Keep only cooldown portion of experiment
X = X(startIdx:end);
Y = Y(startIdx:end);
Z = Z(startIdx:end);
T_accel_clean = T_accel_clean(startIdx:end);


%% ---------------------------------------------------------------
%  Elapsed time
% ----------------------------------------------------------------

t_accel = ...
    (0:length(T_accel_clean)-1)' ...
    * accelSamplePeriod_s / 60;

% Time is now in minutes


%% ---------------------------------------------------------------
%  Remove accelerometer anomalies
% ----------------------------------------------------------------
%
% The three large transient spikes are not representative of the slow
% temperature-dependent response of the accelerometer.
%
% filloutliers identifies points that are many median absolute
% deviations away from the normal signal and replaces them by linear
% interpolation.

X_clean = filloutliers( ...
    X, ...
    'linear', ...
    'median', ...
    'ThresholdFactor',accelOutlierThreshold);

Y_clean = filloutliers( ...
    Y, ...
    'linear', ...
    'median', ...
    'ThresholdFactor',accelOutlierThreshold);

Z_clean = filloutliers( ...
    Z, ...
    'linear', ...
    'median', ...
    'ThresholdFactor',accelOutlierThreshold);


%% ---------------------------------------------------------------
%  Smooth accelerometer signals
% ----------------------------------------------------------------

X_smooth = movmean(X_clean,accelSmoothWindow);
Y_smooth = movmean(Y_clean,accelSmoothWindow);
Z_smooth = movmean(Z_clean,accelSmoothWindow);


%% ---------------------------------------------------------------
%  Establish high-temperature reference
% ----------------------------------------------------------------

% Average the first portion of the cooldown to establish the initial
% sensor bias near maximum temperature.

baselineN = min(500,length(X_clean));

X0 = mean(X_clean(1:baselineN),'omitnan');
Y0 = mean(Y_clean(1:baselineN),'omitnan');
Z0 = mean(Z_clean(1:baselineN),'omitnan');


%% ---------------------------------------------------------------
%  Calculate accelerometer drift
% ----------------------------------------------------------------
%
% Acceleration data are assumed to be reported in g.
%
% Convert the change from g to milli-g:
%
%       1 g = 1000 mg

X_drift = 1000 * (X_smooth - X0);
Y_drift = 1000 * (Y_smooth - Y0);
Z_drift = 1000 * (Z_smooth - Z0);


%% ---------------------------------------------------------------
%  Create accelerometer plot
% ----------------------------------------------------------------

figure( ...
    'Name','Accelerometer Temperature Drift', ...
    'Color','w');


yyaxis left

plot( ...
    t_accel, ...
    X_drift, ...
    'LineWidth',1.5);

hold on

plot( ...
    t_accel, ...
    Y_drift, ...
    'LineWidth',1.5);

plot( ...
    t_accel, ...
    Z_drift, ...
    'LineWidth',1.5);

ylabel('Accelerometer Drift (mg)');


yyaxis right

plot( ...
    t_accel, ...
    T_accel_clean, ...
    'k--', ...
    'LineWidth',1.5);

ylabel('Temperature (^oC)');


xlabel('Elapsed Time During Cooldown (min)');

title( ...
    'Accelerometer Bias Drift During Thermal Cooldown');


legend( ...
    'X Drift', ...
    'Y Drift', ...
    'Z Drift', ...
    'Temperature', ...
    'Location','best');


grid on;
box on;


%% ================================================================
%  PLOT 2 - LOAD CELL TEMPERATURE DRIFT
% =================================================================

%% Load load-cell data

loadData = readmatrix('load_cell_temperature_cleaned.xlsx');

% Only use first two columns
loadData = loadData(:,1:2);

% Remove incomplete rows
loadData = loadData(all(isfinite(loadData),2),:);

T_load = loadData(:,1);
loadSignal = loadData(:,2);


%% ---------------------------------------------------------------
%  Clean load-cell temperature data
% ----------------------------------------------------------------

% Reject physically unrealistic temperature readings
badTemp = ...
    T_load < minValidTemp | ...
    T_load > maxValidTemp;

T_load(badTemp) = NaN;


% Interpolate invalid measurements
T_load = fillmissing( ...
    T_load, ...
    'linear', ...
    'EndValues','nearest');


% Remove isolated temperature spikes
T_load_clean = filloutliers( ...
    T_load, ...
    'linear', ...
    'movmedian', ...
    tempOutlierWindow, ...
    'ThresholdFactor',tempOutlierThreshold);


%% ---------------------------------------------------------------
%  Find beginning of load-cell cooldown
% ----------------------------------------------------------------

T_startDetect = movmean(T_load_clean,31);

[~,startIdx] = max(T_startDetect);


T_load_clean = T_load_clean(startIdx:end);
loadSignal = loadSignal(startIdx:end);


%% ---------------------------------------------------------------
%  Elapsed time
% ----------------------------------------------------------------

t_load = ...
    (0:length(T_load_clean)-1)' ...
    * loadSamplePeriod_s / 60;


%% ---------------------------------------------------------------
%  Remove large load-cell anomalies
% ----------------------------------------------------------------

loadSignalClean = filloutliers( ...
    loadSignal, ...
    'linear', ...
    'movmedian', ...
    25, ...
    'ThresholdFactor',6);


%% ---------------------------------------------------------------
%  Smooth load-cell signal
% ----------------------------------------------------------------
%
% Moving median is useful for the load cell because it suppresses
% short-duration electrical/mechanical spikes while preserving the
% underlying thermal trend.

loadSmooth = movmedian( ...
    loadSignalClean, ...
    loadSmoothWindow);


%% ---------------------------------------------------------------
%  Establish initial load-cell reference
% ----------------------------------------------------------------

baselineN = min(10,length(loadSignalClean));

load0 = median( ...
    loadSignalClean(1:baselineN), ...
    'omitnan');


%% ---------------------------------------------------------------
%  Calculate load-cell drift
% ----------------------------------------------------------------

loadDriftRaw = ...
    loadSignalClean - load0;

loadDriftSmooth = ...
    loadSmooth - load0;


%% ---------------------------------------------------------------
%  Create load-cell plot
% ----------------------------------------------------------------

figure( ...
    'Name','Load Cell Temperature Drift', ...
    'Color','w');


yyaxis left

% Cleaned raw signal shown lightly in background
plot( ...
    t_load, ...
    loadDriftRaw, ...
    'Color',[0.75 0.75 0.75], ...
    'LineWidth',0.5);

hold on


% Smoothed thermal drift
plot( ...
    t_load, ...
    loadDriftSmooth, ...
    'LineWidth',2);

ylabel('Load Cell Drift (raw counts)');


yyaxis right

plot( ...
    t_load, ...
    T_load_clean, ...
    'k--', ...
    'LineWidth',1.5);

ylabel('Temperature (^oC)');


xlabel('Elapsed Time During Cooldown (min)');

title( ...
    'Load Cell Output Drift During Thermal Cooldown');


legend( ...
    'Cleaned Raw Load Cell Drift', ...
    'Smoothed Load Cell Drift', ...
    'Temperature', ...
    'Location','best');


grid on;
box on;