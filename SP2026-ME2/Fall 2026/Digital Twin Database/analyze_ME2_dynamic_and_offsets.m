%% REPS ME-2 Diagnostic Analysis
% Zero-offset-corrected statics + improved vibration analysis
%
% Reads:
%   9_4_26/ME2_master_features.csv
%   9_4_26/cleaned_data/*.csv
%
% Creates:
%   9_4_26/diagnostic_plots/
%   9_4_26/ME2_dynamic_diagnostics.csv
%
% Purpose:
%   1. Correct static load-cell reaction fractions using no-load offsets.
%   2. Analyze accelerometer axes separately.
%   3. Compare commanded vibration frequency to measured response.
%   4. Extract response amplitude AT the commanded frequency.
%
% Author: Blayne Montaque
% Fall 2026

clear;
clc;
close all;

%% ================================================================
% PATHS
% ================================================================

dataDir = fullfile(pwd,'9_4_26');

featureFile = fullfile( ...
    dataDir, ...
    'ME2_master_features.csv');

cleanDir = fullfile( ...
    dataDir, ...
    'cleaned_data');

plotDir = fullfile( ...
    dataDir, ...
    'diagnostic_plots');

if ~isfile(featureFile)
    error('Could not find ME2_master_features.csv.');
end

if ~isfolder(cleanDir)
    error('Could not find cleaned_data folder.');
end

if ~isfolder(plotDir)
    mkdir(plotDir);
end

T = readtable(featureFile);

fprintf('\n============================================================\n');
fprintf(' REPS ME-2 DIAGNOSTIC ANALYSIS\n');
fprintf('============================================================\n');

fprintf('Runs loaded: %d\n\n',height(T));

%% ================================================================
% PART 1
% FIND NO-LOAD LOAD-CELL OFFSETS
% ================================================================

noLoadMask = ...
    T.load_kg == 0 & ...
    T.vibration_pwm == 0;

noLoadT = T(noLoadMask,:);

if isempty(noLoadT)
    error('No no-load / vibration-off runs were found.');
end

LCLeftZero = mean(noLoadT.lc_left_median);
LCRightZero = mean(noLoadT.lc_right_median);

fprintf('Estimated load-cell zero offsets:\n');
fprintf('Left LC zero  = %.2f raw counts\n',LCLeftZero);
fprintf('Right LC zero = %.2f raw counts\n\n',LCRightZero);

%% ================================================================
% PART 2
% ZERO-OFFSET-CORRECT STATIC RUNS
% ================================================================

staticMask = ...
    T.load_kg > 0 & ...
    T.vibration_pwm == 0 & ...
    isfinite(T.load_position_norm);

staticT = T(staticMask,:);

staticT.left_corrected = ...
    staticT.lc_left_median - LCLeftZero;

staticT.right_corrected = ...
    staticT.lc_right_median - LCRightZero;

staticT.total_corrected = ...
    staticT.left_corrected + ...
    staticT.right_corrected;

staticT.left_fraction_corrected = ...
    staticT.left_corrected ./ ...
    staticT.total_corrected;

staticT.right_fraction_corrected = ...
    staticT.right_corrected ./ ...
    staticT.total_corrected;

%% ================================================================
% PLOT A
% CORRECTED LOAD DISTRIBUTION VS IDEAL BEAM
% ================================================================

figure(1);
clf;

loadLevels = unique(staticT.load_kg);
loadLevels = loadLevels(isfinite(loadLevels));

for k = 1:length(loadLevels)

    L = loadLevels(k);

    mask = ...
        abs(staticT.load_kg-L) < 1e-8;

    subset = staticT(mask,:);

    [positionsUnique,~,groupIndex] = ...
        unique(subset.load_position_norm);

    leftFracMean = ...
        accumarray( ...
        groupIndex, ...
        subset.left_fraction_corrected, ...
        [], ...
        @mean);

    leftFracStd = ...
        accumarray( ...
        groupIndex, ...
        subset.left_fraction_corrected, ...
        [], ...
        @std);

    errorbar( ...
        positionsUnique, ...
        leftFracMean, ...
        leftFracStd, ...
        'o-', ...
        'LineWidth',1.5, ...
        'DisplayName',sprintf('%.2f kg',L));

    hold on;

end

xIdeal = linspace(0,1,200);

plot( ...
    xIdeal, ...
    1-xIdeal, ...
    'k--', ...
    'LineWidth',1.5, ...
    'DisplayName','Ideal simply supported beam');

grid on;
box on;

xlabel('Normalized Load Position, x/L');
ylabel('Corrected Left Reaction Fraction');

xlim([0 1]);
ylim([0 1]);

title('Zero-Offset-Corrected Load Distribution');

legend('Location','best');

exportgraphics( ...
    gcf, ...
    fullfile(plotDir, ...
    '01_corrected_load_distribution.png'), ...
    'Resolution',300);

%% ================================================================
% PLOT B
% CORRECTED LEFT/RIGHT LOAD-CELL RESPONSE
% ================================================================

figure(2);
clf;

for k = 1:length(loadLevels)

    L = loadLevels(k);

    mask = ...
        abs(staticT.load_kg-L) < 1e-8;

    subset = staticT(mask,:);

    [positionsUnique,~,groupIndex] = ...
        unique(subset.load_position_norm);

    leftMean = ...
        accumarray( ...
        groupIndex, ...
        subset.left_corrected, ...
        [], ...
        @mean);

    rightMean = ...
        accumarray( ...
        groupIndex, ...
        subset.right_corrected, ...
        [], ...
        @mean);

    plot( ...
        positionsUnique, ...
        leftMean, ...
        'o-', ...
        'LineWidth',1.5, ...
        'DisplayName',sprintf('Left LC, %.2f kg',L));

    hold on;

    plot( ...
        positionsUnique, ...
        rightMean, ...
        's--', ...
        'LineWidth',1.5, ...
        'DisplayName',sprintf('Right LC, %.2f kg',L));

end

grid on;
box on;

xlabel('Normalized Load Position, x/L');
ylabel('Zero-Corrected Load-Cell Output');

xticks([0.25 0.50 0.75]);
xticklabels({'Left','Center','Right'});

title('Zero-Corrected Load-Cell Response vs Position');

legend('Location','best');

exportgraphics( ...
    gcf, ...
    fullfile(plotDir, ...
    '02_corrected_loadcell_response.png'), ...
    'Resolution',300);

%% ================================================================
% PART 3
% DYNAMIC RUN IDENTIFICATION
% ================================================================

vibrationMask = ...
    T.vibration_pwm > 0 & ...
    T.commanded_frequency_Hz > 0;

vibT = T(vibrationMask,:);

fprintf('Dynamic runs identified: %d\n\n',height(vibT));

dynamicRows = {};

%% ================================================================
% PART 4
% PROCESS EVERY VIBRATION RUN AXIS-BY-AXIS
% ================================================================

for i = 1:height(vibT)

    testID = string(vibT.test_id(i));
    originalFilename = string(vibT.filename(i));

    commandedF = vibT.commanded_frequency_Hz(i);
    pwm = vibT.vibration_pwm(i);

    % ------------------------------------------------------------
    % Reconstruct cleaned filename
    % ------------------------------------------------------------

    [~,baseName,~] = fileparts(originalFilename);

    if endsWith(baseName,'.csv','IgnoreCase',true)
        baseName = extractBefore(baseName,strlength(baseName)-3);
    end

    cleanFilename = ...
        baseName + "_clean.csv";

    cleanPath = fullfile( ...
        cleanDir, ...
        cleanFilename);

    if ~isfile(cleanPath)

        warning( ...
            'Cleaned file not found for %s', ...
            testID);

        continue
    end

    D = readtable(cleanPath);

    %% ------------------------------------------------------------
    % Pull acceleration channels
    % ------------------------------------------------------------

    t = D.time_s;
    ax = D.accel_x_g;
    ay = D.accel_y_g;
    az = D.accel_z_g;

    %% ------------------------------------------------------------
    % Prefer motor-on region if available
    % ------------------------------------------------------------

    if ismember('motor_state',D.Properties.VariableNames)

        motorState = upper(string(D.motor_state));

        motorOn = motorState == "ON";

        if sum(motorOn) >= 50

            t = t(motorOn);
            ax = ax(motorOn);
            ay = ay(motorOn);
            az = az(motorOn);

        end
    end

    %% ------------------------------------------------------------
    % Estimate sampling frequency
    % ------------------------------------------------------------

    dt = diff(t);
    dt = dt(isfinite(dt) & dt > 0);

    if isempty(dt)
        Fs = 100;
    else
        Fs = 1/median(dt);
    end

    %% ------------------------------------------------------------
    % Remove mean / DC
    % ------------------------------------------------------------

    ax = ax - mean(ax);
    ay = ay - mean(ay);
    az = az - mean(az);

    %% ------------------------------------------------------------
    % Analyze each axis
    % ------------------------------------------------------------

    outX = analyzeAxis(ax,Fs,commandedF);
    outY = analyzeAxis(ay,Fs,commandedF);
    outZ = analyzeAxis(az,Fs,commandedF);

    %% ------------------------------------------------------------
    % Determine strongest axis AT commanded frequency
    % ------------------------------------------------------------

    cmdAmps = [ ...
        outX.commandAmplitude, ...
        outY.commandAmplitude, ...
        outZ.commandAmplitude ];

    [maxCmdAmplitude,strongAxisIdx] = max(cmdAmps);

    axisNames = ["X","Y","Z"];
    strongestAxis = axisNames(strongAxisIdx);

    %% ------------------------------------------------------------
    % Store one row
    % ------------------------------------------------------------

    dynamicRows(end+1,:) = { ...
        char(testID), ...
        char(originalFilename), ...
        commandedF, ...
        pwm, ...
        Fs, ...
        outX.rms, ...
        outY.rms, ...
        outZ.rms, ...
        outX.dominantFrequency, ...
        outY.dominantFrequency, ...
        outZ.dominantFrequency, ...
        outX.commandAmplitude, ...
        outY.commandAmplitude, ...
        outZ.commandAmplitude, ...
        char(strongestAxis), ...
        maxCmdAmplitude};

end

%% ================================================================
% CREATE DYNAMIC DIAGNOSTIC TABLE
% ================================================================

dynamicNames = { ...
    'test_id', ...
    'filename', ...
    'commanded_frequency_Hz', ...
    'vibration_pwm', ...
    'sampling_frequency_Hz', ...
    'rms_x_g', ...
    'rms_y_g', ...
    'rms_z_g', ...
    'dominant_frequency_x_Hz', ...
    'dominant_frequency_y_Hz', ...
    'dominant_frequency_z_Hz', ...
    'command_amplitude_x', ...
    'command_amplitude_y', ...
    'command_amplitude_z', ...
    'strongest_axis', ...
    'max_command_amplitude'};

dynamicTable = cell2table( ...
    dynamicRows, ...
    'VariableNames',dynamicNames);

outputTable = fullfile( ...
    dataDir, ...
    'ME2_dynamic_diagnostics.csv');

writetable(dynamicTable,outputTable);

%% ================================================================
% PLOT C
% DOMINANT FREQUENCY BY AXIS
% ================================================================

figure(3);
clf;

scatter( ...
    dynamicTable.commanded_frequency_Hz, ...
    dynamicTable.dominant_frequency_x_Hz, ...
    60, ...
    'o');

hold on;

scatter( ...
    dynamicTable.commanded_frequency_Hz, ...
    dynamicTable.dominant_frequency_y_Hz, ...
    60, ...
    's');

scatter( ...
    dynamicTable.commanded_frequency_Hz, ...
    dynamicTable.dominant_frequency_z_Hz, ...
    60, ...
    '^');

freqRange = [ ...
    min(dynamicTable.commanded_frequency_Hz), ...
    max(dynamicTable.commanded_frequency_Hz)];

plot( ...
    freqRange, ...
    freqRange, ...
    'k--', ...
    'LineWidth',1.5);

grid on;
box on;

xlabel('Commanded Frequency [Hz]');
ylabel('Global Dominant Frequency [Hz]');

title('Dominant Frequency by Accelerometer Axis');

legend( ...
    {'X','Y','Z','Ideal f_{dom}=f_{cmd}'}, ...
    'Location','best');

exportgraphics( ...
    gcf, ...
    fullfile(plotDir, ...
    '03_axis_dominant_frequency.png'), ...
    'Resolution',300);

%% ================================================================
% PLOT D
% RESPONSE AT COMMANDED FREQUENCY BY AXIS
% ================================================================

figure(4);
clf;

freqLevels = ...
    unique(dynamicTable.commanded_frequency_Hz);

meanX = nan(size(freqLevels));
meanY = nan(size(freqLevels));
meanZ = nan(size(freqLevels));

stdX = nan(size(freqLevels));
stdY = nan(size(freqLevels));
stdZ = nan(size(freqLevels));

for i = 1:length(freqLevels)

    f0 = freqLevels(i);

    mask = ...
        dynamicTable.commanded_frequency_Hz == f0;

    meanX(i) = mean( ...
        dynamicTable.command_amplitude_x(mask));

    meanY(i) = mean( ...
        dynamicTable.command_amplitude_y(mask));

    meanZ(i) = mean( ...
        dynamicTable.command_amplitude_z(mask));

    stdX(i) = std( ...
        dynamicTable.command_amplitude_x(mask));

    stdY(i) = std( ...
        dynamicTable.command_amplitude_y(mask));

    stdZ(i) = std( ...
        dynamicTable.command_amplitude_z(mask));

end

errorbar( ...
    freqLevels, ...
    meanX, ...
    stdX, ...
    'o-', ...
    'LineWidth',1.5);

hold on;

errorbar( ...
    freqLevels, ...
    meanY, ...
    stdY, ...
    's-', ...
    'LineWidth',1.5);

errorbar( ...
    freqLevels, ...
    meanZ, ...
    stdZ, ...
    '^-', ...
    'LineWidth',1.5);

grid on;
box on;

xlabel('Commanded Excitation Frequency [Hz]');
ylabel('FFT Amplitude at Commanded Frequency');

title('Bridge Frequency Response by Accelerometer Axis');

legend( ...
    {'X','Y','Z'}, ...
    'Location','best');

exportgraphics( ...
    gcf, ...
    fullfile(plotDir, ...
    '04_response_at_commanded_frequency.png'), ...
    'Resolution',300);

%% ================================================================
% PLOT E
% STRONGEST AXIS RESPONSE
% ================================================================

figure(5);
clf;

meanStrong = nan(size(freqLevels));
stdStrong = nan(size(freqLevels));

for i = 1:length(freqLevels)

    mask = ...
        dynamicTable.commanded_frequency_Hz == ...
        freqLevels(i);

    meanStrong(i) = ...
        mean(dynamicTable.max_command_amplitude(mask));

    stdStrong(i) = ...
        std(dynamicTable.max_command_amplitude(mask));

end

errorbar( ...
    freqLevels, ...
    meanStrong, ...
    stdStrong, ...
    'o-', ...
    'LineWidth',1.5);

grid on;
box on;

xlabel('Commanded Excitation Frequency [Hz]');
ylabel('Maximum Axis FFT Amplitude');

title('Frequency Response Using Strongest Accelerometer Axis');

exportgraphics( ...
    gcf, ...
    fullfile(plotDir, ...
    '05_strongest_axis_frequency_response.png'), ...
    'Resolution',300);

%% ================================================================
% PLOT F
% AXIS RMS VS COMMANDED FREQUENCY
% ================================================================

figure(6);
clf;

meanRmsX = nan(size(freqLevels));
meanRmsY = nan(size(freqLevels));
meanRmsZ = nan(size(freqLevels));

stdRmsX = nan(size(freqLevels));
stdRmsY = nan(size(freqLevels));
stdRmsZ = nan(size(freqLevels));

for i = 1:length(freqLevels)

    mask = ...
        dynamicTable.commanded_frequency_Hz == ...
        freqLevels(i);

    meanRmsX(i) = ...
        mean(dynamicTable.rms_x_g(mask));

    meanRmsY(i) = ...
        mean(dynamicTable.rms_y_g(mask));

    meanRmsZ(i) = ...
        mean(dynamicTable.rms_z_g(mask));

    stdRmsX(i) = ...
        std(dynamicTable.rms_x_g(mask));

    stdRmsY(i) = ...
        std(dynamicTable.rms_y_g(mask));

    stdRmsZ(i) = ...
        std(dynamicTable.rms_z_g(mask));

end

errorbar( ...
    freqLevels, ...
    meanRmsX, ...
    stdRmsX, ...
    'o-', ...
    'LineWidth',1.5);

hold on;

errorbar( ...
    freqLevels, ...
    meanRmsY, ...
    stdRmsY, ...
    's-', ...
    'LineWidth',1.5);

errorbar( ...
    freqLevels, ...
    meanRmsZ, ...
    stdRmsZ, ...
    '^-', ...
    'LineWidth',1.5);

grid on;
box on;

xlabel('Commanded Frequency [Hz]');
ylabel('Acceleration RMS [g]');

title('Axis RMS Response vs Excitation Frequency');

legend({'X','Y','Z'},'Location','best');

exportgraphics( ...
    gcf, ...
    fullfile(plotDir, ...
    '06_axis_rms_vs_frequency.png'), ...
    'Resolution',300);

%% ================================================================
% PRINT SUMMARY
% ================================================================

fprintf('\n============================================================\n');
fprintf(' DIAGNOSTIC ANALYSIS COMPLETE\n');
fprintf('============================================================\n');

fprintf('No-load offsets:\n');
fprintf('  Left LC  = %.2f\n',LCLeftZero);
fprintf('  Right LC = %.2f\n\n',LCRightZero);

fprintf('Static runs analyzed: %d\n',height(staticT));
fprintf('Dynamic runs analyzed: %d\n',height(dynamicTable));

fprintf('\nDynamic diagnostics saved to:\n');
fprintf('%s\n',outputTable);

fprintf('\nPlots saved to:\n');
fprintf('%s\n\n',plotDir);

%% ================================================================
% LOCAL FUNCTION
% ================================================================

function out = analyzeAxis(x,Fs,commandedFrequency)

    x = double(x(:));

    x = x(isfinite(x));

    N = length(x);

    out.rms = NaN;
    out.dominantFrequency = NaN;
    out.commandAmplitude = NaN;

    if N < 10
        return
    end

    %% RMS

    out.rms = sqrt(mean(x.^2));

    %% Window signal before FFT

    % Hann window written manually so no extra toolbox is required.
    n = (0:N-1)';

    w = ...
        0.5 - ...
        0.5*cos(2*pi*n/(N-1));

    xw = x .* w;

    %% FFT

    Y = fft(xw);

    % Amplitude correction for window gain.
    coherentGain = mean(w);

    P2 = ...
        abs(Y) / ...
        (N*coherentGain);

    P1 = ...
        P2(1:floor(N/2)+1);

    if length(P1) > 2
        P1(2:end-1) = ...
            2*P1(2:end-1);
    end

    f = ...
        Fs*(0:floor(N/2))/N;

    %% Global dominant frequency

    validBand = ...
        f >= 0.5 & ...
        f <= min(50,Fs/2);

    if any(validBand)

        fBand = f(validBand);
        pBand = P1(validBand);

        [~,idx] = max(pBand);

        out.dominantFrequency = ...
            fBand(idx);
    end

    %% Response amplitude at commanded frequency

    if isfinite(commandedFrequency) && ...
            commandedFrequency > 0

        [~,cmdIdx] = ...
            min(abs(f-commandedFrequency));

        out.commandAmplitude = ...
            P1(cmdIdx);

    end

end