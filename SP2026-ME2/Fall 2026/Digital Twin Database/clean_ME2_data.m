
%% REPS ME-2 DIGITAL TWIN
% Combined Raw Data Cleaning and ML Dataset Organization
%
% Save as:
%   clean_and_organize_ME2_data.m
%
% Folder structure:
%   Project/
%       clean_and_organize_ME2_data.m
%       Twin Data/
%           raw experimental folders
%           first half of temp data.xlsx
%           second half of temp data.xlsx
%
% This script:
%   1. Finds all raw experiment files.
%   2. Parses XLSX, CSV and CSV-in-XLSX exports.
%   3. Cleans sensor measurements.
%   4. Audits timestamp integrity.
%   5. Extracts experiment-level features.
%   6. Organizes cleaned data and metadata.
%   7. Creates group-disjoint ML splits.
%
% Original files are never modified.

clear;
clc;
close all;

%% ================================================================
% USER SETTINGS
% ================================================================

scriptDir = fileparts(mfilename('fullpath'));

if isempty(scriptDir)
    scriptDir = pwd;
end

dataDir = fullfile(scriptDir,'Twin Data');

if ~isfolder(dataDir)
    dataDir = fullfile(pwd,'Twin Data');
end

if ~isfolder(dataDir)
    error('Cannot find Twin Data.');
end

outDir = fullfile(dataDir,'cleaned_data');
modelDir = fullfile(outDir,'model_dataset');

if ~isfolder(outDir), mkdir(outDir); end
if ~isfolder(modelDir), mkdir(modelDir); end

% Acquisition
rawTimeUnit = 'milliseconds';
nominalFs_Hz = 100;

% Sensor limits
accelLimit_g = 16;
tempRange_C = [0 80];

% Cleaning
maxInterpolationGap = 5;
useAccelSpikeFilter = true;
spikeWindow = 21;
spikeThreshold = 10;

% QC
minSamples = 100;
minCoverage = 0.90;
maxInvalidTimeFraction = 0.05;
maxDtCV = 0.10;
maxFlaggedAccelFraction = 0.25;

% ML splitting
randomSeed = 42;
trainFraction = 0.70;
validationFraction = 0.15;

% false = split by repetition group
% true  = hold out entire acquisition batches
splitByBatch = false;

% Thermal recordings
thermalSessionID = "THERMAL_01";
thermalApproxGap_s = 300;

%% ================================================================
% DISCOVER FILES
% ================================================================

files = [
    dir(fullfile(dataDir,'**','*.xlsx'));
    dir(fullfile(dataDir,'**','*.csv'))
];

manifestRecords = struct([]);
featureRows = cell(0,27);
qcRows = cell(0,12);

fprintf('\nREPS ME-2 DATA PIPELINE\n');
fprintf('Discovered %d candidate files.\n\n',numel(files));

%% ================================================================
% MAIN CLEANING LOOP
% ================================================================

for k = 1:numel(files)

    f = files(k);
    sourcePath = fullfile(f.folder,f.name);

    normalizedPath = lower(strrep(sourcePath,'\','/'));

    if contains(normalizedPath,'/cleaned_data/')
        continue
    end

    [~,stem,ext] = fileparts(f.name);

    if startsWith(f.name,'~$') || ...
       endsWith(lower(stem),'_clean') || ...
       contains(lower(f.name),'master_features') || ...
       contains(lower(f.name),'qc_report')
        continue
    end

    relDir = erase(string(f.folder),string(dataDir));
    relDir = regexprep(relDir,'^[\\/]','');

    nameLower = lower(string(f.name));

    thermalPart = 0;

    if contains(nameLower,'first half of temp data')
        thermalPart = 1;
    elseif contains(nameLower,'second half of temp data')
        thermalPart = 2;
    end

    isThermal = thermalPart>0;

    meta = parseMetadata(f.name);

    if ~isThermal && strlength(meta.testID)==0
        continue
    end

    if isThermal
        meta.testID = thermalSessionID + ...
            "_PART" + string(thermalPart);

        meta.loadCode = "";
        meta.positionCode = "";
        meta.vibrationCode = "";
        meta.tempCode = "";

        meta.loadKg = NaN;
        meta.position = NaN;
        meta.pwm = NaN;
        meta.frequencyHz = NaN;

        meta.condition = "THERMAL_TRANSIENT";
    end

    fprintf('[%d/%d] %s\n',k,numel(files),f.name);

    notes = strings(0,1);

    try

        %% --------------------------------------------------------
        % ROBUST FILE PARSING
        % ---------------------------------------------------------

        if strcmpi(ext,'.csv')
            raw = readcell(sourcePath,'FileType','text');
        else
            raw = readcell(sourcePath);
        end

        if isempty(raw)
            error('Empty input file.');
        end

        rawRows = size(raw,1);

        % Standardized numeric matrix:
        % 1 time
        % 2 accel X
        % 3 accel Y
        % 4 accel Z
        % 5 temperature left
        % 6 temperature center
        % 7 temperature right
        % 8 load cell left
        % 9 load cell right
        % 10 motor state

        X = nan(rawRows,9);
        motor = strings(rawRows,1);

        for r = 1:rawRows

            % Some exported XLSX files contain a complete CSV
            % record in the first cell. Others contain 10 cells.
            %
            % Parse either arrangement into scalar fields.

            rowCells = cell(1,10);
            rowCells(:) = {[]};

            firstCell = raw{r,1};

            isDelimited = false;

            if ischar(firstCell) || ...
                    (isstring(firstCell) && isscalar(firstCell))

                firstText = string(firstCell);

                if isscalar(firstText) && ...
                        ~ismissing(firstText) && ...
                        contains(firstText,',')

                    isDelimited = true;
                end
            end

            if isDelimited

                pieces = split(string(firstCell),',');

                nPieces = min(numel(pieces),10);

                for c = 1:nPieces
                    rowCells{c} = pieces(c);
                end

            else

                nColumns = min(size(raw,2),10);

                for c = 1:nColumns
                    rowCells{c} = raw{r,c};
                end
            end

            for c = 1:9
                X(r,c) = scalarNumber(rowCells{c});
            end

            motor(r) = scalarText(rowCells{10});

        end

        motor = upper(strtrim(motor));

        motor(motor=="1" | motor=="TRUE") = "ON";
        motor(motor=="0" | motor=="FALSE") = "OFF";

        %% --------------------------------------------------------
        % ROW ALIGNMENT
        % ---------------------------------------------------------

        % Time and acceleration must exist.
        % Missing individual temperatures or load-cell readings
        % are preserved for channel-level QC.

        aligned = all(isfinite(X(:,1:4)),2);

        if ~isThermal
            aligned = aligned & ...
                (motor=="ON" | motor=="OFF");
        end

        malformedRows = sum(~aligned);

        X = X(aligned,:);
        motor = motor(aligned);

        if size(X,1)<10
            error('Insufficient aligned sensor records.');
        end

        if malformedRows>0
            notes(end+1) = sprintf( ...
                '%d malformed/header rows removed', ...
                malformedRows);
        end

        %% --------------------------------------------------------
        % TIMESTAMP PROCESSING
        % ---------------------------------------------------------

        t = X(:,1);

        if strcmpi(rawTimeUnit,'milliseconds')
            t = t/1000;
        end

        originalTimeCount = numel(t);

        % Identify timestamp resets.
        resetIdx = find(diff(t)<0);

        resetCount = numel(resetIdx);
        resetDiscardedRows = 0;

        if resetCount>0

            notes(end+1) = sprintf( ...
                '%d timestamp resets detected',resetCount);

            boundaries = [1;resetIdx+1;numel(t)+1];
            lengths = diff(boundaries);

            % Keep longest continuous acquisition segment.
            [~,best] = max(lengths);

            first = boundaries(best);
            last = boundaries(best+1)-1;

            resetDiscardedRows = ...
                numel(t)-(last-first+1);

            X = X(first:last,:);
            motor = motor(first:last);
            t = t(first:last);

            notes(end+1) = sprintf( ...
                '%d records outside longest segment omitted', ...
                resetDiscardedRows);
        end

        % Remove duplicate/nonincreasing timestamps.
        keep = [true;diff(t)>0];

        duplicateTimeCount = sum(~keep);

        X = X(keep,:);
        motor = motor(keep);
        t = t(keep);

        if numel(t)<10
            error('Insufficient valid timestamp records.');
        end

        t = t-t(1);

        dt = diff(t);

        if any(~isfinite(dt)) || any(dt<=0)
            error('Invalid timestamps remain after cleaning.');
        end

        medianDt = median(dt);
        meanDt = mean(dt);

        fs = 1/medianDt;
        duration_s = t(end);

        dtCV = std(dt)/meanDt;
        maxGap_s = max(dt);

        invalidTimeFraction = ...
            (resetDiscardedRows+duplicateTimeCount) / ...
            max(originalTimeCount,1);

        gapFraction = mean(dt>1.5*medianDt);

        if dtCV>maxDtCV
            notes(end+1) = 'Irregular sampling intervals';
        end

        if maxGap_s>5*medianDt
            notes(end+1) = 'Large timestamp gaps';
        end

        if invalidTimeFraction>maxInvalidTimeFraction
            notes(end+1) = ...
                'Excessive timestamp-related record loss';
        end

        if fs<1 || fs>5000
            notes(end+1) = ...
                'Unusual estimated sampling frequency';
        end

        if duration_s<=0 || ~isfinite(duration_s)
            error('Invalid duration.');
        end

        %% --------------------------------------------------------
        % SENSOR VALIDATION
        % ---------------------------------------------------------

        A = X(:,2:4);
        T = X(:,5:7);
        LC = X(:,8:9);

        badA = ~isfinite(A) | abs(A)>accelLimit_g;

        if useAccelSpikeFilter

            for j = 1:3

                v = A(:,j);

                if nnz(isfinite(v))>=spikeWindow

                    med = movmedian(v,spikeWindow,'omitnan');

                    dev = abs(v-med);

                    madLocal = movmedian( ...
                        dev,spikeWindow,'omitnan');

                    sigma = 1.4826*madLocal;

                    positiveSigma = sigma( ...
                        isfinite(sigma) & sigma>0);

                    if ~isempty(positiveSigma)

                        sigmaFloor = max( ...
                            median(positiveSigma)*0.05,1e-6);

                        badA(:,j) = badA(:,j) | ...
                            dev>spikeThreshold .* ...
                            max(sigma,sigmaFloor);
                    end
                end
            end
        end

        badT = ~isfinite(T) | ...
            T<tempRange_C(1) | ...
            T>tempRange_C(2);

        badLC = ~isfinite(LC);

        flaggedAccelFraction = ...
            nnz(badA)/max(numel(A),1);

        A(badA) = NaN;
        T(badT) = NaN;
        LC(badLC) = NaN;

        % Fill only short internal missing runs.
        A = fillShortGaps(A,maxInterpolationGap);
        T = fillShortGaps(T,maxInterpolationGap);
        LC = fillShortGaps(LC,maxInterpolationGap);

        coverage = mean(isfinite([A T LC]),1);
        minimumCoverage = min(coverage);

        accelMag = sqrt(sum(A.^2,2));
        accelMag(any(~isfinite(A),2)) = NaN;

        %% --------------------------------------------------------
        % SAVE CLEANED EXPERIMENT
        % ---------------------------------------------------------

        clean = table( ...
            t,A(:,1),A(:,2),A(:,3),accelMag, ...
            T(:,1),T(:,2),T(:,3), ...
            LC(:,1),LC(:,2),motor, ...
            'VariableNames',{ ...
            'time_s', ...
            'accel_x_g','accel_y_g','accel_z_g', ...
            'accel_mag_g', ...
            'temp_left_C','temp_center_C','temp_right_C', ...
            'loadcell_left_raw','loadcell_right_raw', ...
            'motor_state'});

        if isThermal

            outputSubfolder = "thermal_transient";
            outputStem = char(meta.testID);

        else

            outputSubfolder = relDir;
            outputStem = stem;

            if endsWith(lower(outputStem),'.csv')
                outputStem = outputStem(1:end-4);
            end
        end

        destFolder = fullfile( ...
            outDir,char(outputSubfolder));

        if ~isfolder(destFolder)
            mkdir(destFolder);
        end

        outputName = [outputStem '_clean.csv'];

        dest = fullfile(destFolder,outputName);

        writetable(clean,dest);

        relativeCleanPath = string( ...
            fullfile(char(outputSubfolder),outputName));

        %% --------------------------------------------------------
        % DYNAMIC FEATURES
        % ---------------------------------------------------------

        [segStart,segEnd] = ...
            longestTrueRun(motor=="ON");

        if segEnd-segStart+1 < ...
                max(50,round(0.1*numel(t)))

            segStart = 1;
            segEnd = numel(t);
        end

        z = A(segStart:segEnd,3);
        tz = t(segStart:segEnd);

        validZ = isfinite(z);

        z = z(validZ);
        tz = tz(validZ);

        rmsZ = NaN;
        dominantHz = NaN;
        fftPeak = NaN;

        if numel(z)>=10
            rmsZ = sqrt(mean((z-mean(z)).^2));
        end

        % FFT is computed only on a sufficiently regular segment.
        % No artificial resampling is performed here.

        if numel(z)>=100

            dz = diff(tz);
            segmentDt = median(dz);

            uniformSegment = all(dz>0) && ...
                max(abs(dz-segmentDt)) <= ...
                0.2*segmentDt;

            if uniformSegment

                segmentFs = 1/segmentDt;
                n = numel(z);

                y = z-mean(z);

                spectrum = abs(fft(y))/n;
                spectrum = spectrum(1:floor(n/2)+1);

                if numel(spectrum)>2
                    spectrum(2:end-1) = ...
                        2*spectrum(2:end-1);
                end

                frequencies = ...
                    (0:floor(n/2))'*segmentFs/n;

                band = frequencies>=0.5 & ...
                    frequencies<=min(50,segmentFs/2);

                if any(band)

                    indices = find(band);

                    [fftPeak,idx] = ...
                        max(spectrum(band));

                    dominantHz = ...
                        frequencies(indices(idx));
                end
            end
        end

        %% --------------------------------------------------------
        % MASTER FEATURES
        % ---------------------------------------------------------

        tempMean = mean(T,1,'omitnan');

        featureRows(end+1,:) = { ...
            char(meta.testID), ...
            f.name, ...
            char(relDir), ...
            meta.loadKg, ...
            char(meta.loadCode), ...
            meta.position, ...
            char(meta.positionCode), ...
            meta.pwm, ...
            meta.frequencyHz, ...
            char(meta.tempCode), ...
            char(meta.condition), ...
            duration_s,fs, ...
            rawRows,height(clean), ...
            mean(LC(:,1),'omitnan'), ...
            mean(LC(:,2),'omitnan'), ...
            median(LC(:,1),'omitnan'), ...
            median(LC(:,2),'omitnan'), ...
            std(LC(:,1),'omitnan'), ...
            std(LC(:,2),'omitnan'), ...
            tempMean(1),tempMean(2),tempMean(3), ...
            rmsZ,dominantHz,fftPeak};

        %% --------------------------------------------------------
        % METADATA VALIDATION
        % ---------------------------------------------------------

        metadataNotes = strings(0,1);

        if ~isThermal

            if strlength(meta.loadCode)==0
                metadataNotes(end+1) = "UNKNOWN_LOAD";
            end

            if strlength(meta.positionCode)==0 && ...
                    ~isfinite(meta.frequencyHz)

                metadataNotes(end+1) = ...
                    "UNKNOWN_POSITION";
            end

            if strlength(meta.vibrationCode)==0
                metadataNotes(end+1) = ...
                    "UNKNOWN_VIBRATION";
            end
        end

        if isempty(metadataNotes)
            metadataStatus = "OK";
        else
            metadataStatus = "REVIEW";
        end

        %% --------------------------------------------------------
        % DATA QUALITY
        % ---------------------------------------------------------

        fatalReasons = strings(0,1);

        if height(clean)<minSamples
            fatalReasons(end+1) = ...
                "INSUFFICIENT_SAMPLES";
        end

        if minimumCoverage<minCoverage
            fatalReasons(end+1) = ...
                "LOW_SENSOR_COVERAGE";
        end

        if invalidTimeFraction>maxInvalidTimeFraction
            fatalReasons(end+1) = ...
                "EXCESSIVE_TIMESTAMP_LOSS";
        end

        if flaggedAccelFraction>maxFlaggedAccelFraction
            fatalReasons(end+1) = ...
                "EXCESSIVE_ACCEL_FLAGS";
        end

        if isempty(fatalReasons)
            dataStatus = "PASS";
        else
            dataStatus = "FAIL";
        end

        if dtCV<=maxDtCV
            timingStatus = "REGULAR";
        else
            timingStatus = "IRREGULAR";
        end

        if dataStatus=="FAIL"

            eligibility = "EXCLUDE";
            eligibilityReason = ...
                strjoin(fatalReasons," | ");

        elseif metadataStatus=="REVIEW"

            eligibility = "REVIEW";
            eligibilityReason = ...
                strjoin(metadataNotes," | ");

        else

            eligibility = "ELIGIBLE";

            if timingStatus=="IRREGULAR"
                eligibilityReason = "TIMING_WARNING";
            else
                eligibilityReason = "READY";
            end
        end

        if isempty(notes)
            qcStatus = "PASS";
            qcText = "No issues detected";
        else
            qcStatus = "CHECK";
            qcText = strjoin(notes," | ");
        end

        qcRows(end+1,:) = { ...
            char(meta.testID),f.name,char(relDir), ...
            char(qcStatus),char(qcText), ...
            rawRows,height(clean), ...
            malformedRows, ...
            resetCount+duplicateTimeCount, ...
            nnz(badA),nnz(badT),nnz(badLC)};

        %% --------------------------------------------------------
        % EXPERIMENT CLASSIFICATION
        % ---------------------------------------------------------

        if isThermal

            experimentType = "thermal_transient";
            sessionID = thermalSessionID;
            repetitionGroup = thermalSessionID;

        else

            sessionID = relDir;

            experimentType = "baseline";

            if meta.condition=="WIND"

                experimentType = "wind";

            elseif meta.condition=="IMPACT"

                experimentType = "impact";

            elseif isfinite(meta.frequencyHz)

                experimentType = "frequency_sweep";

            elseif meta.loadKg>0 && meta.pwm>0

                experimentType = "load_vibration";

            elseif meta.loadKg>0

                experimentType = "static_load";

            elseif meta.pwm>0

                experimentType = "vibration";
            end

            % Critical fix:
            % Never concatenate string(NaN) into group IDs.
            % Use explicit UNKNOWN placeholders.

            frequencyLabel = "F_UNKNOWN";

            if isfinite(meta.frequencyHz)
                frequencyLabel = ...
                    "F_" + string(meta.frequencyHz);
            end

            loadLabel = safeLabel(meta.loadCode,"L_UNKNOWN");
            positionLabel = safeLabel( ...
                meta.positionCode,"P_UNKNOWN");
            vibrationLabel = safeLabel( ...
                meta.vibrationCode,"V_UNKNOWN");
            conditionLabel = safeLabel( ...
                meta.condition,"NO_DISTURBANCE");
            sessionLabel = safeLabel( ...
                sessionID,"UNKNOWN_SESSION");

            repetitionGroup = strjoin([ ...
                sessionLabel,loadLabel,positionLabel, ...
                vibrationLabel,frequencyLabel, ...
                conditionLabel],"__");
        end

        %% --------------------------------------------------------
        % STORE MANIFEST RECORD
        % ---------------------------------------------------------

        R = struct();

        R.run_id = relativeCleanPath;
        R.test_id = string(meta.testID);
        R.source_file = string(sourcePath);
        R.cleaned_file = relativeCleanPath;

        R.session_id = sessionID;
        R.experiment_type = experimentType;
        R.repetition_group = repetitionGroup;

        R.load_kg = meta.loadKg;
        R.load_position_norm = meta.position;
        R.vibration_pwm = meta.pwm;
        R.commanded_frequency_Hz = meta.frequencyHz;
        R.temperature_code = string(meta.tempCode);
        R.disturbance_type = string(meta.condition);

        R.thermal_part = thermalPart;

        R.thermal_gap_approx_s = NaN;
        if isThermal
            R.thermal_gap_approx_s = thermalApproxGap_s;
        end

        R.sample_count = height(clean);
        R.duration_s = duration_s;

        R.estimated_fs_Hz = fs;
        R.median_dt_s = medianDt;
        R.dt_cv = dtCV;
        R.max_gap_s = maxGap_s;
        R.gap_fraction = gapFraction;

        R.timestamp_reset_count = resetCount;
        R.timestamp_duplicate_count = duplicateTimeCount;
        R.timestamp_discarded_rows = ...
            resetDiscardedRows+duplicateTimeCount;
        R.invalid_time_fraction = invalidTimeFraction;

        R.min_sensor_coverage = minimumCoverage;
        R.flagged_accel_fraction = flaggedAccelFraction;

        R.qc_status = qcStatus;
        R.qc_notes = qcText;
        R.metadata_status = metadataStatus;
        R.data_status = dataStatus;
        R.timing_status = timingStatus;

        R.eligibility_status = eligibility;
        R.eligibility_reason = eligibilityReason;

        R.split = "";

        if isempty(manifestRecords)
            manifestRecords = R;
        else
            manifestRecords(end+1,1) = R;
        end

    catch ME

        warning('FAILED: %s\n%s',sourcePath,ME.message);

        qcRows(end+1,:) = { ...
            char(meta.testID),f.name,char(relDir), ...
            'FAIL',ME.message, ...
            NaN,0,NaN,NaN,NaN,NaN,NaN};
    end
end

%% ================================================================
% MASTER FEATURE AND QC TABLES
% ================================================================

featureNames = { ...
    'test_id','filename','source_subfolder', ...
    'load_kg','load_code', ...
    'load_position_norm','position_code', ...
    'vibration_pwm','commanded_frequency_Hz', ...
    'temperature_code','test_condition', ...
    'duration_s','sampling_frequency_Hz', ...
    'raw_sample_count','clean_sample_count', ...
    'lc_left_mean','lc_right_mean', ...
    'lc_left_median','lc_right_median', ...
    'lc_left_std','lc_right_std', ...
    'temp_left_mean_C','temp_center_mean_C', ...
    'temp_right_mean_C','accel_z_dynamic_rms_g', ...
    'dominant_frequency_z_Hz','fft_peak_z_g'};

qcNames = { ...
    'test_id','filename','source_subfolder', ...
    'qc_status','qc_notes', ...
    'raw_rows','clean_rows','malformed_rows', ...
    'bad_timestamps','flagged_accel_values', ...
    'flagged_temp_values','flagged_loadcell_values'};

F = cell2table(featureRows, ...
    'VariableNames',featureNames);

Q = cell2table(qcRows, ...
    'VariableNames',qcNames);

writetable(F,fullfile(outDir,'ME2_master_features.csv'));
writetable(Q,fullfile(outDir,'ME2_QC_report.csv'));

%% ================================================================
% BUILD MANIFEST
% ================================================================

if isempty(manifestRecords)
    error('No valid cleaned experiments.');
end

M = struct2table(manifestRecords);

% Use full relative file path as unique run identifier.
% Duplicate T#### IDs are warnings, not automatic exclusions.

ids = string(M.test_id);
duplicateIDs = false(height(M),1);

for i = 1:height(M)
    duplicateIDs(i) = sum(ids==ids(i))>1;
end

M.duplicate_test_id = duplicateIDs;

%% ================================================================
% VERIFY GROUP IDENTIFIERS
% ================================================================

groups = string(M.repetition_group);

badGroups = ismissing(groups) | strlength(groups)==0;

if any(badGroups)
    error('%d runs have missing repetition groups.', ...
        sum(badGroups));
end

%% ================================================================
% GROUP-DISJOINT TRAIN / VALIDATION / TEST
% ================================================================

eligible = M.eligibility_status=="ELIGIBLE";

if splitByBatch
    splitGroups = string(M.session_id);
else
    splitGroups = string(M.repetition_group);
end

eligibleGroups = unique(splitGroups(eligible),'stable');

rng(randomSeed);

nGroups = numel(eligibleGroups);

if nGroups>0

    shuffled = eligibleGroups(randperm(nGroups));

    nTrain = floor(trainFraction*nGroups);
    nValidation = floor(validationFraction*nGroups);

    trainGroups = shuffled(1:nTrain);

    validationGroups = shuffled( ...
        nTrain+1:nTrain+nValidation);

    testGroups = shuffled( ...
        nTrain+nValidation+1:end);

    M.split(eligible & ...
        ismember(splitGroups,trainGroups)) = "train";

    M.split(eligible & ...
        ismember(splitGroups,validationGroups)) = ...
        "validation";

    M.split(eligible & ...
        ismember(splitGroups,testGroups)) = "test";
end

M.split(M.eligibility_status=="REVIEW") = "review_only";
M.split(M.eligibility_status=="EXCLUDE") = "excluded";

% Hard stop if any eligible experiment was not assigned.
unassigned = eligible & M.split=="";

if any(unassigned)
    error('%d eligible runs have no ML split.', ...
        sum(unassigned));
end

%% ================================================================
% WRITE MODEL DATASET
% ================================================================

writetable(M,fullfile(modelDir,'manifest.csv'));

writetable(F,fullfile(modelDir,'feature_matrix.csv'));

writetable(M(M.split=="train",:), ...
    fullfile(modelDir,'train_manifest.csv'));

writetable(M(M.split=="validation",:), ...
    fullfile(modelDir,'validation_manifest.csv'));

writetable(M(M.split=="test",:), ...
    fullfile(modelDir,'test_manifest.csv'));

writetable(M(M.eligibility_status~="ELIGIBLE",:), ...
    fullfile(modelDir,'qc_exclusions.csv'));

%% ================================================================
% TIMING QUALITY AUDIT
% ================================================================

timingColumns = { ...
    'run_id','test_id','experiment_type', ...
    'sample_count','duration_s', ...
    'estimated_fs_Hz','median_dt_s', ...
    'dt_cv','max_gap_s','gap_fraction', ...
    'timestamp_reset_count', ...
    'timestamp_duplicate_count', ...
    'timestamp_discarded_rows', ...
    'invalid_time_fraction', ...
    'min_sensor_coverage', ...
    'flagged_accel_fraction', ...
    'data_status','timing_status', ...
    'eligibility_status','eligibility_reason'};

writetable(M(:,timingColumns), ...
    fullfile(modelDir,'timing_quality_audit.csv'));

%% ================================================================
% GROUP SUMMARY
% ================================================================

[G,groupNames] = findgroups(string(M.repetition_group));

runCounts = splitapply(@numel,M.run_id,G);

eligibleCounts = splitapply( ...
    @(x)sum(x=="ELIGIBLE"), ...
    M.eligibility_status,G);

groupTable = table( ...
    groupNames,runCounts,eligibleCounts, ...
    'VariableNames',{ ...
    'repetition_group','run_count','eligible_count'});

writetable(groupTable, ...
    fullfile(modelDir,'experiment_groups.csv'));

%% ================================================================
% DATASET DOCUMENTATION
% ================================================================

readme = [
    "REPS ME-2 DIGITAL TWIN DATASET"
    ""
    "Generated by clean_and_organize_ME2_data.m"
    ""
    "CLEANED DATA"
    "Original raw files are never modified."
    "Cleaned CSVs preserve experimental folder structure."
    "Thermal recordings are stored under thermal_transient."
    ""
    "MANIFEST"
    "One row per successfully cleaned experiment."
    "cleaned_file is relative to Twin Data/cleaned_data."
    "run_id is the unique relative path."
    ""
    "QUALITY CONTROL"
    "PASS means the basic automated checks passed."
    "CHECK indicates warnings requiring interpretation."
    "EXCLUDE means a configured data-quality threshold failed."
    "REVIEW means experimental metadata needs review."
    "ELIGIBLE does not guarantee suitability for every ML model."
    ""
    "TIMESTAMPS"
    "Raw timestamps are interpreted as milliseconds."
    "Cleaned timestamps are elapsed seconds per recording."
    "Sampling irregularity is recorded in the timing audit."
    "No uniform resampling is performed."
    "FFT features remain NaN when sampling is unsuitable."
    "Timestamp resets may cause discarded acquisition segments."
    ""
    "THERMAL EXPERIMENT"
    "THERMAL_01_PART1 and THERMAL_01_PART2 share one session."
    "Recordings were separated by approximately five minutes."
    "The interruption is not filled with synthetic measurements."
    "Both recordings remain in the same ML split."
    ""
    "MODEL SPLITS"
    "Splits are deterministic and group-disjoint."
    "Set splitByBatch=true for acquisition-batch holdout."
    "Current splits are provisional pending label/QC review."
    ""
    "IMPORTANT"
    "Load-cell channels remain raw and uncalibrated."
    "Temperature codes are categories, not measured degrees C."
    "PWM does not establish vibration frequency in Hz."
    "Review timing and experiment balance before training."
];

fid = fopen(fullfile(modelDir,'README.txt'),'w');

if fid>=0
    for i = 1:numel(readme)
        fprintf(fid,'%s\n',char(readme(i)));
    end
    fclose(fid);
end

%% ================================================================
% FINAL REPORT
% ================================================================

fprintf('\n========================================\n');
fprintf(' REPS DATA PIPELINE COMPLETE\n');
fprintf('========================================\n');

fprintf('Cleaned runs:     %d\n',height(M));
fprintf('Failed files:     %d\n',sum(strcmp(Q.qc_status,'FAIL')));

fprintf('\nEligible:         %d\n', ...
    sum(M.eligibility_status=="ELIGIBLE"));

fprintf('Review:           %d\n', ...
    sum(M.eligibility_status=="REVIEW"));

fprintf('Excluded:         %d\n', ...
    sum(M.eligibility_status=="EXCLUDE"));

fprintf('\nTrain:            %d\n',sum(M.split=="train"));
fprintf('Validation:       %d\n',sum(M.split=="validation"));
fprintf('Test:             %d\n',sum(M.split=="test"));

fprintf('\nMissing groups:   %d\n',sum(badGroups));

fprintf('Irregular timing: %d\n', ...
    sum(M.timing_status=="IRREGULAR"));

fprintf('Thermal segments: %d\n', ...
    sum(M.experiment_type=="thermal_transient"));

fprintf('\nOutput: %s\n',outDir);
fprintf('\n');

%% ================================================================
% LOCAL FUNCTIONS
% ================================================================

function n = scalarNumber(x)

    n = NaN;

    if isempty(x)
        return
    end

    if isnumeric(x) || islogical(x)

        if isscalar(x)
            n = double(x);
        end

        return
    end

    if isdatetime(x)

        if isscalar(x)
            n = seconds(x-dateshift(x,'start','day'));
        end

        return
    end

    if isduration(x)

        if isscalar(x)
            n = seconds(x);
        end

        return
    end

    try

        s = string(x);

        if numel(s)~=1 || ismissing(s)
            return
        end

        n = str2double(strtrim(s));

    catch
        n = NaN;
    end
end

function s = scalarText(x)

    s = "";

    if isempty(x)
        return
    end

    try

        value = string(x);

        if numel(value)==1 && ~ismissing(value)
            s = strtrim(value);
        end

    catch
        s = "";
    end
end

function A = fillShortGaps(A,maxGap)

    for j = 1:size(A,2)

        x = A(:,j);
        missing = ~isfinite(x);

        edges = diff([false;missing;false]);

        starts = find(edges==1);
        ends = find(edges==-1)-1;

        for k = 1:numel(starts)

            lo = starts(k);
            hi = ends(k);

            if hi-lo+1<=maxGap && ...
                    lo>1 && hi<numel(x) && ...
                    isfinite(x(lo-1)) && ...
                    isfinite(x(hi+1))

                x(lo:hi) = interp1( ...
                    [lo-1,hi+1], ...
                    x([lo-1,hi+1]), ...
                    (lo:hi)');
            end
        end

        A(:,j) = x;
    end
end

function [a,b] = longestTrueRun(mask)

    edges = diff([false;mask(:);false]);

    starts = find(edges==1);
    ends = find(edges==-1)-1;

    if isempty(starts)
        a = 1;
        b = 0;
        return
    end

    [~,idx] = max(ends-starts+1);

    a = starts(idx);
    b = ends(idx);
end

function m = parseMetadata(filename)

    s = upper(string(filename));

    m.testID = getToken(s,'T\d+');
    m.loadCode = getToken(s,'L\d{2}');
    m.positionCode = getToken(s,'P00|PL|PC|PR');
    m.vibrationCode = getToken(s,'V\d{2}');
    m.tempCode = getToken(s,'TEMP\d{2}');

    f = regexp(char(s), ...
        '(?:^|_)F(\d+)(?=_|\.)', ...
        'tokens','once');

    m.frequencyHz = NaN;

    if ~isempty(f)
        m.frequencyHz = str2double(f{1});
    end

    switch m.loadCode
        case "L00"
            m.loadKg = 0;
        case "L01"
            m.loadKg = 0.25;
        case "L02"
            m.loadKg = 0.50;
        case "L03"
            m.loadKg = 1.00;
        otherwise
            m.loadKg = NaN;
    end

    switch m.positionCode
        case "PL"
            m.position = 0.25;
        case "PC"
            m.position = 0.50;
        case "PR"
            m.position = 0.75;
        otherwise
            m.position = NaN;
    end

    switch m.vibrationCode
        case "V00"
            m.pwm = 0;
        case "V01"
            m.pwm = 64;
        case "V02"
            m.pwm = 128;
        case "V03"
            m.pwm = 192;
        otherwise
            m.pwm = NaN;
    end

    m.condition = "";

    if contains(s,"WIND")
        m.condition = "WIND";
    elseif contains(s,"IMPACT")
        m.condition = "IMPACT";
    end
end

function value = getToken(s,pattern)

    tok = regexp(char(s), ...
        ['(?:^|_)(' pattern ')(?=_|\.)'], ...
        'tokens','once');

    if isempty(tok)
        value = "";
    else
        value = string(tok{1});
    end
end

function label = safeLabel(value,fallback)

    label = string(value);

    if isempty(label) || ...
            any(ismissing(label)) || ...
            any(strlength(label)==0)

        label = string(fallback);
    end

    label = label(1);
end
