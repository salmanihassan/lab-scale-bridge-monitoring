% -------------------------------------------------------------------------
% Experimental Sensor Data Visualization and Frequency-Domain Analysis
%
% This script:
% 1. Reads experimental sensor data from a CSV file
% 2. Extracts load cell, vibration magnitude, and accelerometer signals
% 3. Computes the resultant acceleration magnitude from the X, Y, and Z
%    accelerometer components
% 4. Computes key time-domain signal metrics, including mean, RMS,
%    standard deviation, maximum absolute acceleration, and tolerance band
% 5. Computes the Fast Fourier Transform (FFT) of the resultant
%    acceleration signal
% 6. Identifies the dominant response frequency and corresponding FFT
%    magnitude
% 7. Plots:
%    - Vibration motor magnitude vs time
%    - Load Cell 1 and Load Cell 2 responses vs time
%    - X, Y, and Z accelerometer components vs time
%    - FFT magnitude vs frequency for the resultant acceleration signal
%
% Assumptions:
%   - The input file is a CSV file with NO column headers
%   - Column 1 = Load Cell 1
%   - Column 2 = Load Cell 2
%   - Column 3 = Vibration Magnitude
%   - Column 4 = Accelerometer X
%   - Column 5 = Accelerometer Y
%   - Column 6 = Accelerometer Z
%   - Each data point is collected every 10 ms
% -------------------------------------------------------------------------

clc; clear; close all;

kTol = 2;

%% User settings
fileName = 'data.csv';
dt = 0.01;                      % 10 ms sampling interval [s]
Fs = 1/dt;                      % sampling frequency [Hz]

%% Robust CSV read
raw = readcell(fileName);

if size(raw,2) == 1
    % Case: data stored as comma-separated text in one column
    data = cellfun(@(x) sscanf(x, '%f,%f,%f,%f,%f,%f')', ...
                   raw, 'UniformOutput', false);
    data = vertcat(data{:});
else
    % Case: CSV already parsed into separate numeric columns
    data = cell2mat(raw);
end

%% Extract columns
LC1  = data(:,1);
LC2  = data(:,2);
Vibe = data(:,3);
Xacc = data(:,4);
Yacc = data(:,5);
Zacc = data(:,6);

% Remove invalid rows
validIdx = ~(isnan(LC1) | isnan(LC2) | isnan(Vibe) | ...
             isnan(Xacc) | isnan(Yacc) | isnan(Zacc));

LC1  = LC1(validIdx);
LC2  = LC2(validIdx);
Vibe = Vibe(validIdx);
Xacc = Xacc(validIdx);
Yacc = Yacc(validIdx);
Zacc = Zacc(validIdx);

LC1  = LC1(:);
LC2  = LC2(:);
Vibe = Vibe(:);
Xacc = Xacc(:);
Yacc = Yacc(:);
Zacc = Zacc(:);

%% Time vector
N = length(Xacc);
t = (0:N-1)' * dt;

%% Resultant acceleration magnitude
AccelMag = sqrt(Xacc.^2 + Yacc.^2 + Zacc.^2);

%% Time-domain metrics
aMean = mean(AccelMag);
aRMS  = rms(AccelMag);
aStd  = std(AccelMag);
aMax  = max(abs(AccelMag));
tol   = kTol * aStd;

upperBand = aMean + tol;
lowerBand = aMean - tol;

%% Frequency-domain analysis
aDetrend = AccelMag - mean(AccelMag);

Yfft = fft(aDetrend);
P2 = abs(Yfft/N);
P1 = P2(1:floor(N/2)+1);
P1(2:end-1) = 2*P1(2:end-1);

f = Fs*(0:floor(N/2))/N;

[peakMag, peakIdx] = max(P1);
domFreq = f(peakIdx);

%% Print results
fprintf('\n');
fprintf('Experimental Dynamic Response Results\n\n');

fprintf('Time-domain metrics (resultant acceleration magnitude):\n');
fprintf('    Mean Acceleration   = %.6f g\n', aMean);
fprintf('    RMS Acceleration    = %.6f g\n', aRMS);
fprintf('    Std Acceleration    = %.6f g\n', aStd);
fprintf('    Max |Acceleration|  = %.6f g\n', aMax);
fprintf('    Tolerance Band      = +/- %.6f g\n\n', tol);

fprintf('Frequency-domain metrics:\n');
fprintf('    Dominant Frequency  = %.6f Hz\n', domFreq);
fprintf('    Peak FFT Magnitude  = %.6f\n\n', peakMag);

%% Create centered figure window
figure('Units','normalized', ...
       'Position',[0.06, 0.12, 0.88, 0.72], ...
       'Color','w', ...
       'Name','Experimental Sensor Data Overview');

tiledlayout(2,3,'TileSpacing','compact','Padding','compact');

%% Top left: Vibration motor magnitude
nexttile;
plot(t, Vibe, 'LineWidth', 1.8);
grid on;
box on;
xlabel('Time (s)', 'FontWeight','bold');
ylabel('Vibration Magnitude', 'FontWeight','bold');
title('Vibration Motor Magnitude', 'FontWeight','bold');
set(gca, 'FontSize', 11, 'LineWidth', 1.2);

%% Top middle: Load cell responses
nexttile;
plot(t, LC1, 'LineWidth', 1.8); hold on;
plot(t, LC2, 'LineWidth', 1.8);
grid on;
box on;
xlabel('Time (s)', 'FontWeight','bold');
ylabel('Load Cell Reading', 'FontWeight','bold');
title('Load Cell Responses', 'FontWeight','bold');
legend('Load Cell 1','Load Cell 2','Location','best');
set(gca, 'FontSize', 11, 'LineWidth', 1.2);

%% Top right: Accelerometer components
nexttile;
plot(t, Xacc, 'LineWidth', 1.8); hold on;
plot(t, Yacc, 'LineWidth', 1.8);
plot(t, Zacc, 'LineWidth', 1.8);
grid on;
box on;
xlabel('Time (s)', 'FontWeight','bold');
ylabel('Acceleration (g)', 'FontWeight','bold');
title('Accelerometer Components', 'FontWeight','bold');
legend('X','Y','Z','Location','best');
set(gca, 'FontSize', 11, 'LineWidth', 1.2);

%% Bottom row: FFT spanning all 3 columns
nexttile([1 3]);
plot(f, P1, 'LineWidth', 1.8); hold on;
plot(domFreq, peakMag, 'o', 'MarkerSize', 8, 'LineWidth', 1.8);
grid on;
box on;
xlabel('Frequency (Hz)', 'FontWeight','bold');
ylabel('FFT Magnitude', 'FontWeight','bold');
title('Frequency-Domain Response of Resultant Acceleration', 'FontWeight','bold');
legend('FFT Magnitude','Dominant Frequency','Location','best');
set(gca, 'FontSize', 11, 'LineWidth', 1.2);
xlim([0 Fs/2]);

sgtitle('Experimental Sensor Data Visualization and Dynamic Response Analysis', ...
        'FontWeight','bold', 'FontSize', 14);