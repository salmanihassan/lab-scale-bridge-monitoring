%% REPS ME-2 Digital Twin Data Cleaning
% Batch cleaner for the 9_4_26 bridge baseline dataset.
%
% Expected working directory:
%
%   <current MATLAB folder>\
%       clean_ME2_data.m
%       9_4_26\
%           ME2_T0001_....xlsx
%           ME2_T0002_....xlsx
%           ...
%
% OUTPUT:
%
%   9_4_26\
%       cleaned_data\
%           ME2_T0001_...._clean.csv
%           ...
%
%       ME2_master_features.csv
%       ME2_QC_report.csv
%
% Assumed raw channel order:
%   1  Timestamp / time
%   2  Accel X [g]
%   3  Accel Y [g]
%   4  Accel Z [g]
%   5  Temperature Left [deg C]
%   6  Temperature Center [deg C]
%   7  Temperature Right [deg C]
%   8  Left Load Cell raw
%   9  Right Load Cell raw
%   10 Motor state / command
%
% NOTE:
% This script NEVER modifies the original experimental files.

clear;
clc;
close all;

%% ================================================================
% USER SETTINGS
% ================================================================

dataDir = fullfile(pwd, '9_4_26');
cleanDir = fullfile(dataDir, 'cleaned_data');

% Expected sampling frequency.
% Change this if the actual acquisition frequency is different.
defaultFs_Hz = 100;

% Physical plausibility limits used only for identifying clearly corrupted
% samples. These are intentionally broad.
accelAbsMax_g = 16;

tempMin_C = 0;
tempMax_C = 80;

% Very large jumps relative to neighboring acceleration samples can also be
% rejected. This catches values such as -273 mixed into ~0.03 g data.
useRobustAccelFilter = true;
robustWindow = 21;
robustThreshold = 10;  % multiples of local MAD

% Your current vibration experiment convention.
defaultExcitationFrequency_Hz = 10;

%% ================================================================
% SETUP
% ================================================================

if ~isfolder(dataDir)
    error('Data folder not found: %s', dataDir);
end

if ~isfolder(cleanDir)
    mkdir(cleanDir);
end

% Accept both normal Excel files and files with names such as .csv.xlsx.
files = dir(fullfile(dataDir, '*.xlsx'));

% Also allow real CSV files if you begin exporting them later.
csvFiles = dir(fullfile(dataDir, '*.csv'));

files = [files; csvFiles];

if isempty(files)
    error('No .xlsx or .csv files were found in: %s', dataDir);
end

fprintf('\n============================================================\n');
fprintf(' REPS ME-2 DATA CLEANER\n');
fprintf('============================================================\n');
fprintf('Data folder: %s\n', dataDir);
fprintf('Files found: %d\n\n', numel(files));

%% ================================================================
% MASTER OUTPUT CONTAINERS
% ================================================================

featureRows = {};
qcRows = {};

seenTestIDs = strings(0,1);

%% ================================================================
% PROCESS EVERY FILE
% ================================================================

for fileNum = 1:numel(files)

    filename = files(fileNum).name;
    filepath = fullfile(files(fileNum).folder, filename);

    fprintf('[%3d/%3d] Processing %s\n', ...
        fileNum, numel(files), filename);

    qcMessages = strings(0,1);

    %% ------------------------------------------------------------
    % Parse metadata from filename
    % -------------------------------------------------------------

    meta = parseME2Filename(filename);

    if strlength(meta.testID) == 0
        qcMessages(end+1) = "Could not parse test ID from filename";
    else
        if any(seenTestIDs == meta.testID)
            qcMessages(end+1) = ...
                "DUPLICATE TEST ID: " + meta.testID;
        else
            seenTestIDs(end+1,1) = meta.testID;
        end
    end

    %% ------------------------------------------------------------
    % Read raw file
    % -------------------------------------------------------------

    try
        raw = readcell(filepath);
    catch ME
        warning('Could not read %s: %s', filename, ME.message);

        qcRows(end+1,:) = { ...
            char(meta.testID), filename, ...
            "FAILED_TO_READ", ME.message};

        continue
    end

    if isempty(raw)
        qcRows(end+1,:) = { ...
            char(meta.testID), filename, ...
            "EMPTY_FILE", "File contained no readable data"};

        continue
    end

    %% ------------------------------------------------------------
    % Remove completely empty rows and columns
    % -------------------------------------------------------------

    emptyMask = cellfun(@isCellEmpty, raw);

    emptyRows = all(emptyMask, 2);
    emptyCols = all(emptyMask, 1);

    raw(emptyRows,:) = [];
    raw(:,emptyCols) = [];

    [nRawRows, nRawCols] = size(raw);

    if nRawCols < 10
        qcMessages(end+1) = ...
            "Fewer than 10 populated columns found";
    elseif nRawCols > 10
        qcMessages(end+1) = ...
            sprintf("Found %d populated columns; using first 10", ...
            nRawCols);
    end

    if nRawCols < 9
        qcRows(end+1,:) = { ...
            char(meta.testID), filename, ...
            "BAD_COLUMN_COUNT", ...
            sprintf('Only %d usable columns found',nRawCols)};
        continue
    end

    % Keep the expected acquisition channels only.
    raw = raw(:, 1:min(10,size(raw,2)));

    %% ------------------------------------------------------------
    % Detect whether row 1 contains column headers
    % -------------------------------------------------------------

    hasHeader = detectHeaderRow(raw(1,:));

    if hasHeader
        raw(1,:) = [];
    end

    %% ------------------------------------------------------------
    % Convert columns
    % -------------------------------------------------------------

    Nraw = size(raw,1);

    % Initialize arrays.
    timeRaw   = nan(Nraw,1);
    accelX    = nan(Nraw,1);
    accelY    = nan(Nraw,1);
    accelZ    = nan(Nraw,1);
    tempLeft  = nan(Nraw,1);
    tempCent  = nan(Nraw,1);
    tempRight = nan(Nraw,1);
    lcLeft    = nan(Nraw,1);
    lcRight   = nan(Nraw,1);

    motorState = strings(Nraw,1);

    % Time / timestamp
    for i = 1:Nraw
        timeRaw(i) = convertTimeCell(raw{i,1}, i, defaultFs_Hz);
    end

    % Numeric channels.
    for i = 1:Nraw

        accelX(i)    = cellToDouble(raw{i,2});
        accelY(i)    = cellToDouble(raw{i,3});
        accelZ(i)    = cellToDouble(raw{i,4});
        tempLeft(i)  = cellToDouble(raw{i,5});
        tempCent(i)  = cellToDouble(raw{i,6});
        tempRight(i) = cellToDouble(raw{i,7});
        lcLeft(i)    = cellToDouble(raw{i,8});
        lcRight(i)   = cellToDouble(raw{i,9});

        if size(raw,2) >= 10
            motorState(i) = string(raw{i,10});
        else
            motorState(i) = "";
        end
    end

    %% ------------------------------------------------------------
    % Reconstruct elapsed time
    % -------------------------------------------------------------

    % If timestamps could not be interpreted sensibly, reconstruct time
    % from the expected sampling frequency.

    validTime = isfinite(timeRaw);

    if sum(validTime) >= 2

        t = timeRaw;

        % Convert absolute-looking timestamps into elapsed time.
        firstValid = find(validTime,1,'first');
        t = t - t(firstValid);

        % If conversion resulted in nonsense timing, reconstruct it.
        dtTest = diff(t(validTime));
        dtTest = dtTest(isfinite(dtTest) & dtTest > 0);

        if isempty(dtTest)
            t = (0:Nraw-1)' ./ defaultFs_Hz;
            qcMessages(end+1) = ...
                "Timestamp invalid; reconstructed from nominal Fs";
        end

    else
        t = (0:Nraw-1)' ./ defaultFs_Hz;
        qcMessages(end+1) = ...
            "Timestamp unavailable; reconstructed from nominal Fs";
    end

    %% ------------------------------------------------------------
    % Find invalid acceleration samples
    % -------------------------------------------------------------

    invalidAX = ~isfinite(accelX) | abs(accelX) > accelAbsMax_g;
    invalidAY = ~isfinite(accelY) | abs(accelY) > accelAbsMax_g;
    invalidAZ = ~isfinite(accelZ) | abs(accelZ) > accelAbsMax_g;

    % Robust local-spike detection.
    if useRobustAccelFilter

        invalidAX = invalidAX | ...
            robustSpikeMask(accelX, robustWindow, robustThreshold);

        invalidAY = invalidAY | ...
            robustSpikeMask(accelY, robustWindow, robustThreshold);

        invalidAZ = invalidAZ | ...
            robustSpikeMask(accelZ, robustWindow, robustThreshold);
    end

    numBadAccel = ...
        sum(invalidAX) + sum(invalidAY) + sum(invalidAZ);

    if numBadAccel > 0
        qcMessages(end+1) = ...
            sprintf("%d corrupted acceleration values corrected", ...
            numBadAccel);
    end

    accelX(invalidAX) = NaN;
    accelY(invalidAY) = NaN;
    accelZ(invalidAZ) = NaN;

    % Fill isolated bad readings by linear interpolation.
    accelX = fillmissing(accelX,'linear','EndValues','nearest');
    accelY = fillmissing(accelY,'linear','EndValues','nearest');
    accelZ = fillmissing(accelZ,'linear','EndValues','nearest');

    %% ------------------------------------------------------------
    % Temperature validation
    % -------------------------------------------------------------

    invalidTL = ...
        ~isfinite(tempLeft) | ...
        tempLeft < tempMin_C | tempLeft > tempMax_C;

    invalidTC = ...
        ~isfinite(tempCent) | ...
        tempCent < tempMin_C | tempCent > tempMax_C;

    invalidTR = ...
        ~isfinite(tempRight) | ...
        tempRight < tempMin_C | tempRight > tempMax_C;

    numBadTemp = sum(invalidTL) + sum(invalidTC) + sum(invalidTR);

    if numBadTemp > 0
        qcMessages(end+1) = ...
            sprintf("%d invalid temperature values corrected", ...
            numBadTemp);
    end

    tempLeft(invalidTL) = NaN;
    tempCent(invalidTC) = NaN;
    tempRight(invalidTR) = NaN;

    tempLeft  = fillmissing(tempLeft,'linear','EndValues','nearest');
    tempCent  = fillmissing(tempCent,'linear','EndValues','nearest');
    tempRight = fillmissing(tempRight,'linear','EndValues','nearest');

    %% ------------------------------------------------------------
    % Load-cell validation
    % -------------------------------------------------------------

    invalidLCLeft  = ~isfinite(lcLeft);
    invalidLCRight = ~isfinite(lcRight);

    numBadLC = sum(invalidLCLeft) + sum(invalidLCRight);

    if numBadLC > 0
        qcMessages(end+1) = ...
            sprintf("%d invalid load-cell readings corrected", ...
            numBadLC);
    end

    lcLeft(invalidLCLeft) = NaN;
    lcRight(invalidLCRight) = NaN;

    lcLeft = fillmissing(lcLeft,'linear','EndValues','nearest');
    lcRight = fillmissing(lcRight,'linear','EndValues','nearest');

    %% ------------------------------------------------------------
    % Normalize motor state strings
    % -------------------------------------------------------------

    motorState = upper(strtrim(motorState));

    motorState( ...
        motorState == "1" | ...
        motorState == "TRUE") = "ON";

    motorState( ...
        motorState == "0" | ...
        motorState == "FALSE") = "OFF";

    %% ------------------------------------------------------------
    % Remove rows that remain unusable
    % -------------------------------------------------------------

    validRows = ...
        isfinite(t) & ...
        isfinite(accelX) & ...
        isfinite(accelY) & ...
        isfinite(accelZ) & ...
        isfinite(tempLeft) & ...
        isfinite(tempCent) & ...
        isfinite(tempRight) & ...
        isfinite(lcLeft) & ...
        isfinite(lcRight);

    numRowsRemoved = sum(~validRows);

    if numRowsRemoved > 0
        qcMessages(end+1) = ...
            sprintf("%d rows removed after cleaning", ...
            numRowsRemoved);
    end

    t         = t(validRows);
    accelX    = accelX(validRows);
    accelY    = accelY(validRows);
    accelZ    = accelZ(validRows);
    tempLeft  = tempLeft(validRows);
    tempCent  = tempCent(validRows);
    tempRight = tempRight(validRows);
    lcLeft    = lcLeft(validRows);
    lcRight   = lcRight(validRows);
    motorState = motorState(validRows);

    Nclean = length(t);

    if Nclean < 10
        qcRows(end+1,:) = { ...
            char(meta.testID), filename, ...
            "INSUFFICIENT_DATA", ...
            "Fewer than 10 clean rows remain"};

        continue
    end

    %% ------------------------------------------------------------
    % Estimate sampling rate
    % -------------------------------------------------------------

    dt = diff(t);
    dt = dt(isfinite(dt) & dt > 0);

    if isempty(dt)

        Fs = defaultFs_Hz;

    else

        Fs = 1 / median(dt);

        % Reject obviously unreasonable inferred values.
        if ~isfinite(Fs) || Fs < 1 || Fs > 5000
            Fs = defaultFs_Hz;
            qcMessages(end+1) = ...
                "Unreasonable inferred Fs; nominal Fs used";
        end
    end

    %% ------------------------------------------------------------
    % Resultant acceleration
    % -------------------------------------------------------------

    accelMag = sqrt( ...
        accelX.^2 + ...
        accelY.^2 + ...
        accelZ.^2 );

    %% ------------------------------------------------------------
    % Determine vibration-analysis segment
    % -------------------------------------------------------------

    motorOn = motorState == "ON";

    % If ON/OFF state exists, analyze motor-on samples for vibration.
    % Otherwise analyze the entire file.
    if sum(motorOn) >= max(50, round(0.10*Nclean))
        dynMask = motorOn;
    else
        dynMask = true(Nclean,1);
    end

    dynAccel = accelMag(dynMask);

    %% ------------------------------------------------------------
    % Dynamic features
    % -------------------------------------------------------------

    accelRMS = sqrt(mean(dynAccel.^2));

    accelMean = mean(dynAccel);

    % Remove DC component before FFT.
    xFFT = dynAccel - mean(dynAccel);

    NfftData = length(xFFT);

    if NfftData >= 4

        Y = fft(xFFT);

        P2 = abs(Y/NfftData);
        P1 = P2(1:floor(NfftData/2)+1);

        if length(P1) > 2
            P1(2:end-1) = 2*P1(2:end-1);
        end

        f = Fs*(0:floor(NfftData/2))/NfftData;

        % Ignore DC.
        P1(1) = 0;

        % Restrict search to a sensible bridge band.
        freqMask = f >= 0.5 & f <= min(50,Fs/2);

        if any(freqMask)

            fSearch = f(freqMask);
            pSearch = P1(freqMask);

            [fftPeak, peakIdx] = max(pSearch);
            dominantFreq = fSearch(peakIdx);

        else
            dominantFreq = NaN;
            fftPeak = NaN;
        end

    else
        dominantFreq = NaN;
        fftPeak = NaN;
    end

    %% ------------------------------------------------------------
    % Static / environmental features
    % -------------------------------------------------------------

    lcLeftMean   = mean(lcLeft);
    lcRightMean  = mean(lcRight);

    lcLeftMedian  = median(lcLeft);
    lcRightMedian = median(lcRight);

    lcLeftStd  = std(lcLeft);
    lcRightStd = std(lcRight);

    meanTempLeft  = mean(tempLeft);
    meanTempCent  = mean(tempCent);
    meanTempRight = mean(tempRight);

    tempGradient = ...
        max([meanTempLeft meanTempCent meanTempRight]) - ...
        min([meanTempLeft meanTempCent meanTempRight]);

    duration_s = t(end) - t(1);

    %% ------------------------------------------------------------
    % Determine nominal input conditions from filename
    % -------------------------------------------------------------

    load_kg = loadCodeToKg(meta.loadCode);

    loadPosition = positionCodeToNormalized(meta.positionCode);

    vibrationPWM = vibrationCodeToPWM(meta.vibrationCode);

    % Frequency-sweep filenames contain explicit F05/F10/F15.
    if isfinite(meta.frequencyHz)

        commandedFrequency_Hz = meta.frequencyHz;
        frequencySource = "filename";

    elseif vibrationPWM > 0

        commandedFrequency_Hz = defaultExcitationFrequency_Hz;
        frequencySource = "default_10Hz";

    else

        commandedFrequency_Hz = 0;
        frequencySource = "motor_off";
    end

    %% ------------------------------------------------------------
    % Save cleaned time-series CSV
    % -------------------------------------------------------------

    cleanTable = table( ...
        t, ...
        accelX, ...
        accelY, ...
        accelZ, ...
        accelMag, ...
        tempLeft, ...
        tempCent, ...
        tempRight, ...
        lcLeft, ...
        lcRight, ...
        motorState, ...
        'VariableNames', { ...
        'time_s', ...
        'accel_x_g', ...
        'accel_y_g', ...
        'accel_z_g', ...
        'accel_mag_g', ...
        'temp_left_C', ...
        'temp_center_C', ...
        'temp_right_C', ...
        'loadcell_left_raw', ...
        'loadcell_right_raw', ...
        'motor_state'});

    [~,baseName,~] = fileparts(filename);

    % Handles names ending in ".csv.xlsx"
    if endsWith(baseName,'.csv','IgnoreCase',true)
        baseName = extractBefore(baseName, strlength(baseName)-3);
    end

    cleanFilename = [char(baseName) '_clean.csv'];

    writetable( ...
        cleanTable, ...
        fullfile(cleanDir,cleanFilename));

    %% ------------------------------------------------------------
    % Add row to master feature table
    % -------------------------------------------------------------

    featureRows(end+1,:) = { ...
        char(meta.testID), ...
        filename, ...
        load_kg, ...
        char(meta.loadCode), ...
        loadPosition, ...
        char(meta.positionCode), ...
        vibrationPWM, ...
        commandedFrequency_Hz, ...
        char(frequencySource), ...
        char(meta.tempCode), ...
        duration_s, ...
        Fs, ...
        Nraw, ...
        Nclean, ...
        lcLeftMean, ...
        lcRightMean, ...
        lcLeftMedian, ...
        lcRightMedian, ...
        lcLeftStd, ...
        lcRightStd, ...
        meanTempLeft, ...
        meanTempCent, ...
        meanTempRight, ...
        tempGradient, ...
        accelMean, ...
        accelRMS, ...
        dominantFreq, ...
        fftPeak};

    %% ------------------------------------------------------------
    % QC status
    % -------------------------------------------------------------

    if isempty(qcMessages)
        qcStatus = "PASS";
        qcText = "No issues detected";
    else
        qcStatus = "CHECK";
        qcText = strjoin(qcMessages," | ");
    end

    qcRows(end+1,:) = { ...
        char(meta.testID), ...
        filename, ...
        char(qcStatus), ...
        char(qcText)};

end

%% ================================================================
% CREATE MASTER FEATURE TABLE
% ================================================================

featureNames = { ...
    'test_id', ...
    'filename', ...
    'load_kg', ...
    'load_code', ...
    'load_position_norm', ...
    'position_code', ...
    'vibration_pwm', ...
    'commanded_frequency_Hz', ...
    'frequency_source', ...
    'temperature_code', ...
    'duration_s', ...
    'sampling_frequency_Hz', ...
    'raw_sample_count', ...
    'clean_sample_count', ...
    'lc_left_mean', ...
    'lc_right_mean', ...
    'lc_left_median', ...
    'lc_right_median', ...
    'lc_left_std', ...
    'lc_right_std', ...
    'temp_left_mean_C', ...
    'temp_center_mean_C', ...
    'temp_right_mean_C', ...
    'temperature_gradient_C', ...
    'accel_magnitude_mean_g', ...
    'accel_rms_g', ...
    'dominant_frequency_Hz', ...
    'fft_peak_magnitude'};

if ~isempty(featureRows)

    masterFeatures = cell2table( ...
        featureRows, ...
        'VariableNames',featureNames);

    writetable( ...
        masterFeatures, ...
        fullfile(dataDir,'ME2_master_features.csv'));

else

    warning('No valid feature rows were produced.');
end

%% ================================================================
% CREATE QC REPORT
% ================================================================

if ~isempty(qcRows)

    qcTable = cell2table( ...
        qcRows, ...
        'VariableNames', { ...
        'test_id', ...
        'filename', ...
        'qc_status', ...
        'qc_notes'});

    writetable( ...
        qcTable, ...
        fullfile(dataDir,'ME2_QC_report.csv'));

end

%% ================================================================
% SUMMARY
% ================================================================

fprintf('\n============================================================\n');
fprintf(' CLEANING COMPLETE\n');
fprintf('============================================================\n');

fprintf('Original files processed: %d\n',numel(files));

if exist('masterFeatures','var')
    fprintf('Valid runs:              %d\n',height(masterFeatures));
end

fprintf('\nCleaned files:\n%s\n',cleanDir);
fprintf('\nMaster feature table:\n%s\n', ...
    fullfile(dataDir,'ME2_master_features.csv'));

fprintf('\nQC report:\n%s\n\n', ...
    fullfile(dataDir,'ME2_QC_report.csv'));

%% ================================================================
% LOCAL FUNCTIONS
% ================================================================

function tf = isCellEmpty(x)

    if isempty(x)
        tf = true;
        return
    end

    if isnumeric(x)
        tf = isempty(x) || (isscalar(x) && isnan(x));
        return
    end

    s = string(x);
    tf = ismissing(s) || strlength(strtrim(s)) == 0;

end


function value = cellToDouble(x)

    if isnumeric(x)

        if isempty(x)
            value = NaN;
        else
            value = double(x(1));
        end

        return
    end

    if islogical(x)
        value = double(x);
        return
    end

    s = strtrim(string(x));

    value = str2double(s);

end


function tf = detectHeaderRow(row)

    % A real data row should contain mostly numeric values in columns 2-9.
    %
    % A header such as "Accel X", "Temperature", etc. will not.

    n = min(length(row),9);

    numericCount = 0;

    for k = 2:n

        val = cellToDouble(row{k});

        if isfinite(val)
            numericCount = numericCount + 1;
        end
    end

    tf = numericCount < 5;

end


function t = convertTimeCell(x,index,Fs)

    % Handles:
    % - numeric timestamps
    % - Excel datetime/duration
    % - time strings
    % - missing timestamps

    if isnumeric(x)

        if isempty(x)
            t = (index-1)/Fs;
        else
            t = double(x(1));
        end

        return
    end

    if isdatetime(x)
        t = seconds(x - dateshift(x,'start','day'));
        return
    end

    if isduration(x)
        t = seconds(x);
        return
    end

    s = strtrim(string(x));

    value = str2double(s);

    if isfinite(value)
        t = value;
        return
    end

    % Try interpreting a HH:mm:ss style timestamp.
    try
        d = duration(s,'InputFormat','hh:mm:ss.SSS');
        t = seconds(d);
        return
    catch
    end

    try
        d = duration(s,'InputFormat','hh:mm:ss');
        t = seconds(d);
        return
    catch
    end

    t = (index-1)/Fs;

end


function mask = robustSpikeMask(x,windowSize,threshold)

    x = double(x(:));

    mask = false(size(x));

    good = isfinite(x);

    if sum(good) < windowSize
        return
    end

    temp = x;

    % Temporarily interpolate missing values so moving statistics work.
    temp = fillmissing(temp,'linear','EndValues','nearest');

    localMedian = movmedian(temp,windowSize);

    deviation = abs(temp-localMedian);

    localMAD = movmedian( ...
        abs(temp-localMedian), ...
        windowSize);

    % Robust equivalent of standard deviation.
    localSigma = 1.4826*localMAD;

    % Prevent essentially-zero MAD from making the detector hypersensitive.
    floorSigma = max(median(localSigma(localSigma>0)),1e-6);

    localSigma(localSigma < floorSigma*0.05) = floorSigma*0.05;

    mask = deviation > threshold.*localSigma;

end


function meta = parseME2Filename(filename)

    meta.testID = "";
    meta.loadCode = "";
    meta.positionCode = "";
    meta.vibrationCode = "";
    meta.tempCode = "";
    meta.frequencyHz = NaN;

    name = upper(string(filename));

    % Test ID
    tok = regexp(name,'T\d{4}','match','once');
    if ~isempty(tok)
        meta.testID = string(tok);
    end

    % Load code
    tok = regexp(name,'L\d{2}','match','once');
    if ~isempty(tok)
        meta.loadCode = string(tok);
    end

    % Position
    tok = regexp(name,'_(P00|PL|PC|PR)_','tokens','once');
    if ~isempty(tok)
        meta.positionCode = string(tok{1});
    end

    % Vibration
    tok = regexp(name,'V\d{2}','match','once');
    if ~isempty(tok)
        meta.vibrationCode = string(tok);
    end

    % Temperature
    tok = regexp(name,'TEMP\d{2}','match','once');
    if ~isempty(tok)
        meta.tempCode = string(tok);
    end

    % Explicit frequency code e.g. F05 / F10 / F15
    tok = regexp(name,'_F(\d{2})_','tokens','once');

    if ~isempty(tok)
        meta.frequencyHz = str2double(tok{1});
    end

end


function kg = loadCodeToKg(code)

    switch upper(string(code))

        case "L00"
            kg = 0;

        case "L01"
            kg = 0.25;

        case "L02"
            kg = 0.50;

        case "L03"
            kg = 1.00;

        otherwise
            kg = NaN;
    end

end


function x = positionCodeToNormalized(code)

    switch upper(string(code))

        case "PL"
            x = 0.25;

        case "PC"
            x = 0.50;

        case "PR"
            x = 0.75;

        case "P00"
            x = NaN;

        otherwise
            x = NaN;
    end

end


function pwm = vibrationCodeToPWM(code)

    switch upper(string(code))

        case "V00"
            pwm = 0;

        case "V01"
            pwm = 64;

        case "V02"
            pwm = 128;

        case "V03"
            pwm = 192;

        otherwise
            pwm = NaN;
    end

end