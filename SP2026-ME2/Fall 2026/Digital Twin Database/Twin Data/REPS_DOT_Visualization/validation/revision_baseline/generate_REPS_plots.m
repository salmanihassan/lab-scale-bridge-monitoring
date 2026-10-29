function generate_REPS_plots(dataRoot)
%GENERATE_REPS_PLOTS Read-only analysis of existing cleaned REPS recordings.
% From Twin Data: addpath('REPS_DOT_Visualization'); generate_REPS_plots
% Outputs are restricted to REPS_DOT_Visualization. No raw files are read.
% See README.md for selection, timing rules, uncertainty and provenance.

out = fileparts(mfilename('fullpath'));
if nargin < 1, dataRoot = fileparts(out); end
cleanRoot = fullfile(dataRoot,'cleaned_data');
assert(isfolder(cleanRoot),'Cleaned dataset is missing. Raw data will not be substituted.');
cats = ["01_Experimental_Overview","02_Static_Load","03_Load_Position", ...
    "04_Vibration","05_Frequency_Analysis","06_Combined_Load_Vibration", ...
    "07_Temperature_Drift","08_Wind_Impact","09_Comparative_Summary"];
for c = cats, ensureDir(fullfile(out,'figures',c)); end
ensureDir(fullfile(out,'report','figures'));
ensureDir(fullfile(out,'validation'));
diary(fullfile(out,'execution_log.txt')); diaryGuard=onCleanup(@() diary('off')); %#ok<NASGU>
fprintf('\nREPS visualization: %s | MATLAB %s\n',datestr(now,31),version);
before = fingerprints(cleanRoot);
writetable(before,fullfile(out,'validation','input_hashes_before.csv'));
[M,notes] = loadMetadata(cleanRoot);
assert(~any(excluded(M.cleaned_file) | excluded(M.source_subfolder)),'Excluded batch leaked through metadata gate.');
n = height(M); D=cell(n,1); S=cell(n,1); B=cell(n,1);
channels = ["accel_x_g","accel_y_g","accel_z_g","temp_left_C", ...
    "temp_center_C","temp_right_C","loadcell_left_raw","loadcell_right_raw"];
coverage = nan(n,8);
vars = ["duration_s","valid_span_s","median_fs_Hz","effective_fs_Hz", ...
    "gap_count","max_gap_s","dt_cv","reset_count","duplicate_count", ...
    "lc_left_median","lc_right_median","lc_asymmetry","lc_left_std","lc_right_std", ...
    "rms_x_g","rms_y_g","rms_z_g","peak_z_g","temp_left_mean_C", ...
    "temp_center_mean_C","temp_right_mean_C","on_fraction","longest_interval_s", ...
    "spectral_fs_Hz","dominant_Hz","fft_peak_g","lc_extreme_count","lc_left_max","lc_right_max"];
for v=vars, M.(v)=nan(n,1); end
M.spectral_eligible=false(n,1); M.spectral_reason=strings(n,1);
M.spectral_start_s=nan(n,1); M.spectral_end_s=nan(n,1);
M.spectral_jitter_fraction=nan(n,1); M.analysis_notes=strings(n,1);
signalOK = exist('pwelch','file')==2 && exist('hann','file')==2 && ...
    exist('spectrogram','file')==2 && license('test','Signal_Toolbox');
if ~signalOK
    notes(end+1)="Signal Processing Toolbox functions are unavailable; Welch PSD, windowed spectra and spectrograms will be skipped.";
end
for note=reshape(notes,1,[]), fprintf('NOTE: %s\n',note); end
for i=1:n
    p=fullfile(cleanRoot,M.cleaned_file(i)); assert(isfile(p),'Missing cleaned file: %s',p);
    T=readtable(p,'TextType','string','VariableNamingRule','preserve');
    assert(all(ismember(["time_s",channels,"motor_state"],string(T.Properties.VariableNames))), ...
        'Unexpected schema/units: %s',p);
    t=T.time_s; A=T{:,channels(1:3)}; L=T{:,channels(7:8)};
    assert(isnumeric(t) && all(isfinite(t)),'Invalid time column: %s',p);
    dt=diff(t); positive=dt(dt>0); assert(~isempty(positive),'No increasing times: %s',p);
    md=median(positive); M.duration_s(i)=max(t)-min(t);
    M.median_fs_Hz(i)=1/md; M.effective_fs_Hz(i)=(numel(t)-1)/M.duration_s(i);
    M.gap_count(i)=nnz(dt>1.5*md); M.max_gap_s(i)=max(dt);
    M.dt_cv(i)=std(positive)/mean(positive); M.reset_count(i)=nnz(dt<0);
    M.duplicate_count(i)=nnz(dt==0); coverage(i,:)=mean(isfinite(T{:,channels}),1);
    V=isfinite(t)&any(isfinite(T{:,channels}),2);
    M.valid_span_s(i)=max(t(V))-min(t(V));
    M.lc_left_median(i)=median(L(:,1),'omitnan'); M.lc_right_median(i)=median(L(:,2),'omitnan');
    M.lc_asymmetry(i)=M.lc_left_median(i)-M.lc_right_median(i);
    M.lc_left_std(i)=std(L(:,1),'omitnan'); M.lc_right_std(i)=std(L(:,2),'omitnan');
    % This is an audit flag only: no sensor value is replaced or removed.
    M.lc_extreme_count(i)=nnz(abs(L)>=8388607 & isfinite(L));
    M.lc_left_max(i)=max(L(:,1),[],'omitnan'); M.lc_right_max(i)=max(L(:,2),[],'omitnan');
    Z=nan(size(A));
    for j=1:3, Z(:,j)=linearResidual(t,A(:,j)); end
    M{i,{'rms_x_g','rms_y_g','rms_z_g'}}=sqrt(mean(Z.^2,1,'omitnan'));
    M.peak_z_g(i)=max(abs(Z(:,3)),[],'omitnan');
    M{i,{'temp_left_mean_C','temp_center_mean_C','temp_right_mean_C'}}=mean(T{:,channels(4:6)},1,'omitnan');
    motor=upper(string(T.motor_state)); known=motor=="ON"|motor=="OFF";
    if any(known), M.on_fraction(i)=mean(motor(known)=="ON"); end
    [spec,reason]=spectralSegment(t,A(:,3),signalOK);
    M.longest_interval_s(i)=spec.duration; M.spectral_reason(i)=reason;
    M.spectral_eligible(i)=spec.valid; M.spectral_fs_Hz(i)=spec.fs;
    M.spectral_start_s(i)=spec.start; M.spectral_end_s(i)=spec.stop;
    M.spectral_jitter_fraction(i)=spec.jitter;
    if spec.valid, M.dominant_Hz(i)=spec.peakHz; M.fft_peak_g(i)=spec.peakAmplitude; end
    S{i}=spec;
    if M.reset_count(i)>0 || M.duplicate_count(i)>0
        M.analysis_notes(i)=M.analysis_notes(i)+" Nonincreasing timestamps: time-domain summaries only; no sorting or reset repair.";
    end
    if M.lc_extreme_count(i)>0
        M.analysis_notes(i)=M.analysis_notes(i)+sprintf(' %d load-cell entries at/beyond 8,388,607 counts; retained, with robust medians used for aggregates.',M.lc_extreme_count(i));
    end
    if M.test_id(i)=="T0", M.analysis_notes(i)=M.analysis_notes(i)+" Suspicious T0 identifier retained under unique file path; not renamed."; end
    D{i}=struct('T',T,'t',t,'z',Z,'dt',md);
    if M.category(i)=="Thermal", B{i}=thermalBins(T); end
end
M.min_coverage=min(coverage,[],2);
writetable(M,fullfile(out,'run_metrics.csv'));
writetable(M(:,["run_id","test_id","category","spectral_eligible","spectral_reason", ...
    "longest_interval_s","spectral_start_s","spectral_end_s","spectral_fs_Hz", ...
    "spectral_jitter_fraction","gap_count","max_gap_s","reset_count","duplicate_count"]), ...
    fullfile(out,'frequency_audit.csv'));
fprintf('Retained %d recordings; %d spectral intervals pass.\n',n,nnz(M.spectral_eligible));

% Okabe-Ito palette. Use markers as well as colors for comparison plots.
palette=[0 .447 .698; .835 .369 0; 0 .620 .451; .800 .475 .655; .337 .706 .914; .902 .624 0; .2 .2 .2];
old=get(groot,{'defaultAxesFontSize','defaultAxesFontName','defaultLineLineWidth', ...
    'defaultAxesColorOrder','defaultTextInterpreter','defaultLegendInterpreter','defaultAxesTickLabelInterpreter'});
set(groot,'defaultAxesFontSize',11,'defaultAxesFontName','Arial','defaultLineLineWidth',1.25, ...
    'defaultAxesColorOrder',palette,'defaultTextInterpreter','none', ...
    'defaultLegendInterpreter','none','defaultAxesTickLabelInterpreter','none');
styleGuard=onCleanup(@() set(groot,{'defaultAxesFontSize','defaultAxesFontName','defaultLineLineWidth', ...
    'defaultAxesColorOrder','defaultTextInterpreter','defaultLegendInterpreter','defaultAxesTickLabelInterpreter'},old)); %#ok<NASGU>
P=struct([]); allIdx=(1:n)';
common="All retained source QC statuses are carried into run_metrics.csv. Existing cleaning included spike filtering and short-gap interpolation; original peaks cannot be recovered. No additional sensor cleaning is performed.";
static=find(M.category=="Static load"); vib=find(M.category=="Vibration");
combined=find(M.category=="Load + vibration"); thermal=find(M.category=="Thermal");
disturb=find(ismember(M.category,["Wind","Impact"])); freq=find(M.category=="Frequency sweep");

%% 1. Overview (four figures)
f=newFig(); countBars(M.category,'Experimental category','Recording count');
title('Retained experimental coverage');
add(f,1,'experimental_categories',allIdx,'Counts of cleaned recordings by experimental category.', ...
    sprintf('%d recordings are retained, including %d thermal segments from one session; %d have CHECK status.',n,numel(thermal),nnz(M.qc_status=="CHECK")), ...
    'Count metadata rows after path-based exclusion; thermal segments count as recordings, not independent sessions.', ...
    'Counts describe available recordings, not independent statistical replicates.');
f=newFig(); tiledlayout(1,2);
nexttile; countBars(numberLabels(M.load_kg,' kg'),'Applied mass','Recording count'); title('Applied mass coverage');
nexttile; countBars(numberLabels(M.vibration_pwm,' PWM'),'Motor command','Recording count'); title('Vibration command coverage');
add(f,1,'condition_counts',allIdx,'Coverage of applied mass and motor PWM, including explicit unknown values.', ...
    sprintf('Applied mass is unknown for %d recordings and PWM is unknown for %d recordings.',nnz(~isfinite(M.load_kg)),nnz(~isfinite(M.vibration_pwm))), ...
    'Categorical counts; missing values are a separate category.', 'PWM is a control command, not a measured frequency in Hz.');
f=newFig(); tiledlayout(1,2); nexttile;
histogram(M.effective_fs_Hz,15); xlabel('Samples / timestamp span [s^{-1}]'); ylabel('Recordings'); title('Effective recording rate'); grid on;
nexttile; histogram(M.duration_s,15); xlabel('Timestamp span [s]'); ylabel('Recordings'); title('Recorded timestamp spans'); grid on;
add(f,1,'timing_distributions',allIdx,'Effective sample rate and timestamp-span distributions.', ...
    sprintf('Median-interval rates range %.3f--%.3f Hz; effective rates range %.3f--%.3f samples/s. Timestamp spans range %.3f--%.3f s.',min(M.median_fs_Hz),max(M.median_fs_Hz),min(M.effective_fs_Hz),max(M.effective_fs_Hz),min(M.duration_s),max(M.duration_s)), ...
    'Median-interval rate = 1/median(dt); effective rate = (N-1)/(last-first timestamp).', ...
    'Neither rate establishes uniform acquisition. Thermal part 2 contains a leading all-missing record and a long timestamp gap.');
f=newFig(); tiledlayout(1,2,'TileSpacing','compact'); nexttile;
batches=unique(M.source_subfolder,'stable'); cov=nan(numel(batches),8);
for j=1:numel(batches), cov(j,:)=100*mean(coverage(M.source_subfolder==batches(j),:),1); end
imagesc(cov,[90 100]); colorbar; xticks(1:8); xticklabels({'ax','ay','az','T left','T center','T right','LC left','LC right'}); xtickangle(45);
yticks(1:numel(batches)); yticklabels(shortBatch(batches)); title('Mean finite coverage [%]');
nexttile; countBars(M.qc_status,'Existing QC status','Recording count'); title('Original QC report');
add(f,1,'sensor_coverage_qc',allIdx,'Finite sensor coverage by batch and unchanged source QC status.', ...
    sprintf('Minimum per-run channel coverage is %.2f percent. %d recordings carry CHECK status.',100*min(coverage,[],'all'),nnz(M.qc_status=="CHECK")), ...
    'Per-run finite fraction, averaged equally across runs within each batch.', ...
    'Finite coverage does not certify accuracy, absence of clipping, or independence of interpolated samples.');

%% 2. Static load (four figures)
if ~isempty(static)
    reps=representatives(static,M.load_position_norm,M.lc_left_median,M);
    f=newFig(); tiledlayout(2,1); for j=1:2
        nexttile; hold on; for k=reps', plotGap(D{k}.t,D{k}.T{:,channels(6+j)},D{k}.dt,labelRun(M,k)); end
        xlabel('Elapsed time [s]'); ylabel('Load-cell output [counts]'); title(sprintf('%s load cell: representative static recordings',side(j))); legend('Location','eastoutside'); grid on;
    end
    add(f,2,'static_time_histories',reps,'Representative static load-cell time histories by position.',metricRange(M.lc_left_median(reps),'Left run medians','counts'), ...
        'One representative per position: nearest group-median left output, with deterministic filename tie breaking; no waveform smoothing.', ...
        'Representative selection is descriptive; different masses or batches can occur. Conditions are given in the legend.');
    f=newFig(); tiledlayout(1,2); for j=1:2
        nexttile; groupResponse(M,static,'load_kg',choose(j,'lc_left_median','lc_right_median'),["source_subfolder","load_position_norm"]);
        xlabel('Applied mass [kg]'); ylabel('Run median [counts]'); title(side(j)+' load-cell response');
    end
    add(f,2,'static_mass_response',static,'Run-median load-cell output versus applied mass, separated by batch and position.', ...
        metricRange(M.lc_left_median(static),'Left run medians','counts')+" "+metricRange(M.lc_right_median(static),'Right run medians','counts'), ...
        'Points are condition means of run medians; error bars are between-run sample SD when n >= 2.', ...
        'The 0.25 kg data are from September 25; 0.5 and 1 kg static data are from September 18. No across-batch calibration line is fitted.');
    f=newFig(); groupResponse(M,static,'load_kg','lc_asymmetry',["source_subfolder","load_position_norm"]);
    xlabel('Applied mass [kg]'); ylabel('Left median - right median [counts]'); title('Static load-cell output asymmetry');
    add(f,2,'static_asymmetry',static,'Difference between left and right run-median load-cell outputs.',metricRange(M.lc_asymmetry(static),'Output asymmetry','counts'), ...
        'Difference of uncalibrated run medians; means and sample SD across matched repetitions.', ...
        'Different gains and offsets prevent interpreting this quantity as a force imbalance.');
    f=newFig(); repeatabilityPlot(M,static); title('Static repetition spread');
    add(f,2,'static_repeatability',static,'Individual run medians within equivalent static conditions.', ...
        sprintf('%d recordings form %d batch/mass/position groups; raw load-cell extremes occur %d times in these recordings.',numel(static),numel(unique(conditionKey(M,static))),sum(M.lc_extreme_count(static))), ...
        'Every dot is one run median; groups require identical batch, mass, position, PWM, frequency label and disturbance.', ...
        'Repeated readings within a recording are not treated as independent replicates. Extremes remain in the source data.');
end

%% 3. Position (three figures)
if ~isempty(static)
    f=newFig(); tiledlayout(1,2); for j=1:2
        nexttile; groupResponse(M,static,'load_position_norm',choose(j,'lc_left_median','lc_right_median'),["source_subfolder","load_kg"]); positionAxis(); ylabel('Run median [counts]'); title(side(j)+' output by position');
    end
    add(f,3,'position_response',static,'Left, center and right loading positions at matched mass and batch.',metricRange(M.lc_asymmetry(static),'Left-minus-right median difference','counts'), ...
        'Condition mean and between-run sample SD of raw run medians.', 'Sensor offsets are not zeroed; these are measured outputs, not calibrated support reactions.');
    f=newFig(); groupResponse(M,static,'load_position_norm','lc_asymmetry',["source_subfolder","load_kg"]); positionAxis(); ylabel('Left median - right median [counts]'); title('Position sensitivity of output asymmetry');
    add(f,3,'position_asymmetry',static,'Position-dependent raw output asymmetry within mass and batch strata.',metricRange(M.lc_asymmetry(static),'Observed asymmetry','counts'), ...
        'Difference of run medians, followed by within-condition mean and SD.', 'The sign does not establish a physical load split without calibration.');
    M.raw_left_share=M.lc_left_median./(abs(M.lc_left_median)+abs(M.lc_right_median));
    M.raw_left_share(abs(M.lc_left_median)+abs(M.lc_right_median)==0)=NaN;
    f=newFig(); groupResponse(M,static,'load_position_norm','raw_left_share',["source_subfolder","load_kg"]); positionAxis(); ylabel('L / (|L| + |R|) [dimensionless]'); title('Relative raw signal contribution');
    add(f,3,'relative_signal_distribution',static,'Normalized left raw-output contribution by load position.',metricRange(M.raw_left_share(static),'Normalized contribution','dimensionless'), ...
        'L and R are raw run medians; denominator-zero cases stay missing.', ...
        'This is a signal ratio only. It is not the fraction of applied force carried by a support; offsets and gains are uncalibrated.');
end

%% 4. Vibration (four figures)
if ~isempty(vib)
    reps=representatives(vib,M.vibration_pwm,M.rms_z_g,M);
    f=newFig(); tiledlayout(2,1); nexttile; hold on;
    for k=reps', plotGap(D{k}.t,D{k}.T.accel_z_g,D{k}.dt,labelRun(M,k)); end
    xlabel('Elapsed time [s]'); ylabel('Cleaned acceleration z [g]'); title('Acceleration including static offset'); grid on; legend('Location','eastoutside');
    nexttile; hold on; for k=reps', plotGap(D{k}.t,D{k}.z(:,3),D{k}.dt,labelRun(M,k)); end
    xlabel('Elapsed time [s]'); ylabel('Dynamic acceleration z [g]'); title('Linear trend removed using actual timestamps'); grid on; legend('Location','eastoutside');
    add(f,4,'vibration_time_histories',reps,'Cleaned and linearly detrended acceleration in representative no-load vibration runs.',metricRange(M.rms_z_g(reps),'Dynamic z RMS','g'), ...
        'Representative nearest the median RMS within each PWM setting. OLS linear trend against actual timestamps is subtracted; all finite samples contribute.', ...
        'Cleaned acceleration is not original raw data. RMS includes both logged motor states, preserving the commanded switching cycle.');
    f=newFig(); groupResponse(M,vib,'vibration_pwm','rms_z_g',"source_subfolder"); xlabel('Motor PWM command'); ylabel('Dynamic z RMS [g]'); title('No-load vibration RMS by PWM');
    add(f,4,'vibration_rms',vib,'Dynamic acceleration RMS across the no-load PWM series.',metricRange(M.rms_z_g(vib),'Run-level dynamic z RMS','g'), ...
        'Sample-weighted RMS of timestamp-linear residuals; mean and between-run SD within PWM.', 'No causal or monotonic trend is assumed; no-load runs originate in one batch.');
    f=newFig(); groupResponse(M,vib,'vibration_pwm','peak_z_g',"source_subfolder"); xlabel('Motor PWM command'); ylabel('Maximum |dynamic z| [g]'); title('Observed vibration peaks by PWM');
    add(f,4,'vibration_peaks',vib,'Largest observed absolute detrended z acceleration in each no-load vibration run.',metricRange(M.peak_z_g(vib),'Observed dynamic peaks','g'), ...
        'Maximum absolute finite residual, without additional smoothing or resampling.', 'Earlier cleaning may have removed spikes. These are peaks in the cleaned records, not guaranteed physical maxima.');
    f=newFig(); hold on; for j=1:3
        values=M{vib,vars(14+j)}; scatter(M.vibration_pwm(vib)+3*(j-2),values,45,palette(j,:),'filled','DisplayName',sprintf('%s axis','x'+j-1));
    end
    xlabel('Motor PWM command (small offsets separate axes)'); ylabel('Dynamic RMS [g]'); title('Axis-resolved dynamic response'); legend('Location','best'); grid on;
    add(f,4,'vibration_axes',vib,'Axis-resolved RMS for the same no-load recordings.', ...
        sprintf('Median x/y/z RMS is %.5g / %.5g / %.5g g.',median(M.rms_x_g(vib)),median(M.rms_y_g(vib)),median(M.rms_z_g(vib))), ...
        'Same timestamp-based linear detrending separately on each acceleration axis; individual run points.', 'Axis directions use the cleaned schema. Sensor orientation and cross-axis calibration have not been independently verified.');
end

%% 5. Timing diagnostics and conditional frequency-domain figures
spectralCandidates=unique([vib;freq;combined;disturb]);
if ~isempty(spectralCandidates)
    reps=representatives(spectralCandidates,M.category,M.longest_interval_s,M);
    f=newFig(); tiledlayout(2,1); nexttile; hold on;
    for k=reps', tt=D{k}.t; plot(tt(2:end),diff(tt),'.','DisplayName',M.category(k)+" / "+M.test_id(k)); end
    set(gca,'YScale','log'); xlabel('Elapsed time [s]'); ylabel('Timestamp increment [s]'); title('Jitter and recurring acquisition gaps'); grid on; legend('Location','eastoutside');
    nexttile; scatter(1:numel(spectralCandidates),M.longest_interval_s(spectralCandidates),25,'filled'); yline(4,'--','Minimum 4 s');
    xlabel('Retained frequency-analysis candidate index'); ylabel('Longest valid interval [s]'); title('Continuous interval eligibility'); grid on;
    add(f,5,'timestamp_integrity',spectralCandidates,'Timestamp increments in representative runs and the longest continuous valid intervals in all candidates.', ...
        sprintf('%d candidates have longest intervals from %.3f to %.3f s; %d pass spectral rules.',numel(spectralCandidates),min(M.longest_interval_s(spectralCandidates)),max(M.longest_interval_s(spectralCandidates)),nnz(M.spectral_eligible(spectralCandidates))), ...
        'Split on missing acceleration, nonincreasing timestamps or dt > 1.5 times median dt. Require >= 4 s, >= 256 samples and maximum interval jitter <= 20 percent.', ...
        'Large gaps are treated as missing acquisition, not jitter. Cleaned files cannot determine whether packet loss or blocking acquisition caused them.');
    f=newFig(); countBars(M.spectral_reason(spectralCandidates),'Eligibility result','Recordings'); title('Frequency-domain analysis audit');
    add(f,5,'spectral_eligibility',spectralCandidates,'Reasons for admitting or withholding frequency-domain analysis.',sprintf('%d of %d candidates are accepted for spectral execution; %d pass timing but lack the required toolbox functions.',nnz(M.spectral_eligible(spectralCandidates)),numel(spectralCandidates),nnz(M.spectral_reason(spectralCandidates)=="Signal Processing Toolbox unavailable")), ...
        'Every candidate is audited independently. Signal Processing Toolbox availability is also required.', ...
        'No FFT, PSD, spectrogram or dominant-frequency claim is made for rejected intervals. PWM is never converted to Hz.');
    valid=spectralCandidates(M.spectral_eligible(spectralCandidates));
    if ~isempty(valid)
        reps=representatives(valid,M.vibration_pwm,M.rms_z_g,M); reps=reps(1:min(4,numel(reps)));
        for kind=1:2
            f=newFig(); hold on; for k=reps'
                s=S{k}; if kind==1, plot(s.f,s.amplitude,'DisplayName',labelRun(M,k)); else, plot(s.pf,s.psd,'DisplayName',labelRun(M,k)); end
            end
            xlabel('Frequency [Hz]'); ylabel(choose(kind,'One-sided amplitude [g]','Welch PSD [g^2/Hz]')); title(choose(kind,'Windowed acceleration spectra','Welch acceleration power spectra')); grid on; legend('Location','eastoutside');
            add(f,5,choose(kind,'fft_amplitude','welch_psd'),reps,'Frequency content of accepted continuous intervals.',metricRange(M.dominant_Hz(reps),'Largest spectral peak above 0.5 Hz','Hz'), ...
                spectralDescription(M,reps),'Linear interpolation can attenuate high frequencies. Peaks are response peaks, not verified structural modes or excitation frequencies.');
        end
        k=reps(1); s=S{k}; f=newFig(); imagesc(s.st,s.sf,10*log10(max(s.sp,realmin))); axis xy; colorbar; xlabel('Time within accepted interval [s]'); ylabel('Frequency [Hz]'); title('Spectrogram: '+M.test_id(k));
        add(f,5,'spectrogram',k,'Time-localized PSD on one accepted interval.',sprintf('Accepted interval %.3f--%.3f s; fs %.6g Hz.',s.start,s.stop,s.fs),spectralDescription(M,k),'Color is PSD in dB relative to 1 g^2/Hz; window resolution limits interpretation.');
        fv=intersect(valid,freq);
        if ~isempty(fv)
            f=newFig(); scatter(M.commanded_frequency_Hz(fv),M.dominant_Hz(fv),45,'filled'); xlabel('Filename-commanded frequency [Hz]'); ylabel('Largest response peak [Hz]'); title('Command label versus measured response peak'); grid on;
            add(f,5,'commanded_vs_peak',fv,'Known filename frequency labels compared with accepted response-spectrum peaks.',metricRange(M.dominant_Hz(fv),'Measured response peaks','Hz'),spectralDescription(M,fv),'Command labels are not tachometer measurements and do not validate excitation frequency.');
        end
    end
end

%% 6. Combined conditions (four figures)
if ~isempty(combined)
    f=newFig(); tiledlayout(1,3); for pos=[.25 .5 .75]
        nexttile; ix=combined(M.load_position_norm(combined)==pos); groupResponse(M,ix,'load_kg','rms_z_g',"vibration_pwm"); xlabel('Applied mass [kg]'); ylabel('Dynamic z RMS [g]'); title(positionName(pos)+' loading');
    end
    add(f,6,'combined_rms_mass',combined,'Acceleration RMS versus mass within matching position and PWM strata of September 25.',metricRange(M.rms_z_g(combined),'Dynamic z RMS','g'), ...
        'Run-level timestamp-linear residual RMS; each point is a condition mean with between-run sample SD.', 'Unequal repetition counts and uncontrolled temperature can affect apparent load dependence.');
    f=newFig(); tiledlayout(1,3); for pwm=[64 128 192]
        nexttile; ix=combined(M.vibration_pwm(combined)==pwm); groupResponse(M,ix,'load_position_norm','rms_z_g',"load_kg"); positionAxis(); ylabel('Dynamic z RMS [g]'); title(sprintf('PWM %d',pwm));
    end
    add(f,6,'combined_rms_position',combined,'Position sensitivity of vibration RMS at matching mass and PWM.',metricRange(M.rms_z_g(combined),'Observed run RMS','g'), ...
        'Condition means and sample SD within the same acquisition batch.', 'These comparisons show associations under recorded conditions, not isolated causal effects.');
    reps=representatives(combined,M.vibration_pwm,M.rms_z_g,M);
    f=newFig(); tiledlayout(2,1); for j=1:2
        nexttile; hold on; for k=reps', plotGap(D{k}.t,D{k}.T{:,channels(6+j)},D{k}.dt,labelRun(M,k)); end
        xlabel('Elapsed time [s]'); ylabel('Load-cell output [counts]'); title(side(j)+' load cell during commanded vibration'); legend('Location','eastoutside'); grid on;
    end
    add(f,6,'combined_loadcell_histories',reps,'Representative load-cell histories during combined loading and vibration.',metricRange(M.lc_left_median(reps),'Left run medians','counts'), ...
        'Nearest median-RMS representative per PWM; unsmoothed cleaned traces with lines broken at acquisition gaps.', 'Mass and position of representatives are listed; the traces alone do not isolate PWM effects.');
    pair=unique([static;combined]); pair=pair(M.source_subfolder(pair)=="9_25_loadvib" & M.load_kg(pair)==.25);
    if any(M.vibration_pwm(pair)==0) && any(M.vibration_pwm(pair)>0)
        f=newFig(); groupResponse(M,pair,'vibration_pwm','rms_z_g',"load_position_norm"); xlabel('Motor PWM command'); ylabel('Dynamic z RMS [g]'); title('Matched 0.25 kg recordings: vibration off and on');
        add(f,6,'matched_vibration_off_on',pair,'Same-batch 0.25 kg comparison of vibration-disabled and vibration-enabled recordings.',matchedChange(M,pair), ...
            'Batch, mass and position are held fixed; full-recording detrending is identical for all runs.', 'No same-batch unloaded vibration baseline exists here; an unloaded-versus-loaded causal comparison is therefore omitted.');
    end
end

%% 7. Thermal drift (five figures)
thermalStats=table();
if ~isempty(thermal)
    f=newFig(); tiledlayout(1,numel(thermal)); for k=thermal'
        nexttile; T=D{k}.T; valid=any(isfinite(T{:,channels}),2); t0=D{k}.t(find(valid,1)); hold on;
        for j=1:3, plotGap(D{k}.t-t0,T{:,channels(3+j)},D{k}.dt,side3(j)); end
        xlabel('Elapsed time within segment [s]'); ylabel('Temperature [deg C]'); title(M.test_id(k)); grid on; legend('Location','best');
    end
    add(f,7,'thermal_temperature',thermal,'Temperature channels in separately displayed THERMAL_01 recording segments.', ...
        thermalRanges(D,thermal), 'Each axis starts at its first finite sensor row; no shared clock is inferred and no missing interval is bridged.', ...
        'Segments belong to one session with an approximately five-minute interruption. The leading 539.826 s timestamp gap in part 2 is not interpreted as the inter-segment interruption.');
    f=newFig(); tiledlayout(2,numel(thermal)); slopes=nan(numel(thermal),5); fitR2=slopes;
    for j=1:2, for h=1:numel(thermal)
        k=thermal(h); b=B{k}; nexttile; [slope,r2]=scatterFit(b.temp_left_C,b{:,channels(6+j)}); slopes(h,j)=slope; fitR2(h,j)=r2;
        xlabel('Left temperature, 1 s median [deg C]'); ylabel(side(j)+' LC, 1 s median [counts]'); title(M.test_id(k));
    end, end
    add(f,7,'thermal_loadcell_temperature',thermal,'Load-cell versus left temperature using occupied one-second bins in each thermal segment.', ...
        sprintf('Left LC slopes by segment: %s counts/deg C. Right LC slopes: %s counts/deg C.',join(compose("%.5g",slopes(:,1)),', '),join(compose("%.5g",slopes(:,2)),', ')), ...
        'One-second medians of paired finite observations; OLS trends fitted separately if temperature span >= 1 deg C and >= 20 paired bins.', ...
        'Median binning reduces sensitivity to retained gross artifacts. Both temperature and output change with time; slopes are observational, not compensation coefficients.');
    f=newFig(); tiledlayout(3,numel(thermal)); for j=1:3, for h=1:numel(thermal)
        k=thermal(h); b=B{k}; nexttile; [slopes(h,2+j),fitR2(h,2+j)]=scatterFit(b.temp_left_C,b{:,channels(j)});
        xlabel('Left temperature, 1 s median [deg C]'); ylabel(sprintf('a_%s, 1 s median [g]','x'+j-1)); title(M.test_id(k));
    end, end
    add(f,7,'thermal_accel_temperature',thermal,'Acceleration offsets versus temperature in separate thermal segments.', ...
        sprintf('z-axis fitted slopes by segment are %s g/deg C, with R-squared %s.',join(compose("%.5g",slopes(:,5)),', '),join(compose("%.3f",fitR2(:,5)),', ')), ...
        'One-second paired medians, then segment-specific OLS; these are cleaned acceleration levels including gravity and offset.', ...
        'Orientation, excitation and temporal drift are confounders. Repeated segments are not independent thermal sessions.');
    f=newFig(); tiledlayout(2,numel(thermal)); for j=1:2, for k=thermal'
        b=B{k}; nexttile; y=b{:,channels(6+j)}; base=median(y(b.time_s<=min(b.time_s)+5),'omitnan');
        plotGap(b.time_s-min(b.time_s),y-base,1,M.test_id(k)); xlabel('Elapsed time within segment [s]'); ylabel('Change from first 5 s median [counts]'); title(M.test_id(k)+' / '+side(j)); grid on;
    end, end
    add(f,7,'thermal_elapsed_drift',thermal,'Within-segment load-cell changes relative to the first five seconds of occupied one-second bins.', ...
        driftSummary(B,thermal), 'One-second medians; initial baseline is computed separately for each segment and sensor.', ...
        'The segment offset is intentionally not interpreted as a measured continuous drift across the interruption.');
    f=newFig(); tiledlayout(1,2); nexttile; bar(slopes(:,1:2)'); xticklabels({'Left LC','Right LC'}); ylabel('Observed slope [counts/deg C]'); title('Load-cell association'); legend(M.test_id(thermal),'Location','best'); grid on;
    nexttile; bar(slopes(:,3:5)'); xticklabels({'x','y','z'}); ylabel('Observed slope [g/deg C]'); title('Acceleration-level association'); legend(M.test_id(thermal),'Location','best'); grid on;
    add(f,7,'thermal_sensitivity_summary',thermal,'Comparison of fitted thermal associations by sensor and segment.', ...
        sprintf('Thermal fits use %d and %d occupied one-second bins; R-squared ranges %.3f--%.3f.',height(B{thermal(1)}),height(B{thermal(end)}),min(fitR2,[],'all','omitnan'),max(fitR2,[],'all','omitnan')), ...
        'OLS slopes on paired one-second medians; no confidence interval assumes independent time samples.', ...
        'Slopes describe this session only. A validated compensation model requires independent thermal cycles and controlled loading.');
    thermalChannels=channels([7 8 1 2 3]);
    for h=1:numel(thermal), for j=1:5
        thermalStats=[thermalStats; table(M.test_id(thermal(h)),thermalChannels(j),slopes(h,j),fitR2(h,j), ...
            'VariableNames',{'segment','sensor','slope_per_C','r_squared'})]; %#ok<AGROW>
    end, end
    writetable(thermalStats,fullfile(out,'thermal_fits.csv'));
end

%% 8. Disturbances (three figures)
if ~isempty(disturb)
    reps=representatives(disturb,M.category+" PWM "+string(M.vibration_pwm),M.peak_z_g,M);
    f=newFig(); tiledlayout(numel(reps),1); for k=reps'
        nexttile; plotGap(D{k}.t,D{k}.z(:,3),D{k}.dt,labelRun(M,k)); xlabel('Elapsed time [s]'); ylabel('Dynamic z [g]'); title(labelRun(M,k)+' / '+M.category(k)); grid on;
    end
    add(f,8,'disturbance_transients',reps,'Representative cleaned disturbance recordings with timestamp-linear trends removed.',metricRange(M.peak_z_g(reps),'Largest observed absolute z residual','g'), ...
        'Nearest median peak by disturbance type and PWM; no additional smoothing.', ...
        'Exact impact times, wind speeds and impact forces are unknown. Gaps and earlier spike filtering limit peak interpretation.');
    f=newFig(); tiledlayout(1,2); labels=M.category(disturb)+" "+M.test_id(disturb)+" / PWM "+string(M.vibration_pwm(disturb));
    nexttile; bar(M.rms_z_g(disturb)); xticks(1:numel(disturb)); xticklabels(labels); xtickangle(35); ylabel('Dynamic z RMS [g]'); title('Run-level RMS'); grid on;
    nexttile; bar(M.peak_z_g(disturb)); xticks(1:numel(disturb)); xticklabels(labels); xtickangle(35); ylabel('Maximum |dynamic z| [g]'); title('Observed peak response'); grid on;
    add(f,8,'disturbance_metrics',disturb,'Disturbance RMS and observed peak by run, with motor commands identified.',metricRange(M.rms_z_g(disturb),'Run RMS','g')+" "+metricRange(M.peak_z_g(disturb),'Run peaks','g'), ...
        'Identical detrending and sample-weighted metrics; all runs shown separately.', ...
        'Wind at PWM 192 is confounded with motor operation. A certified undisturbed baseline is unavailable in this batch.');
    impact=disturb(M.category(disturb)=="Impact");
    if ~isempty(impact)
        f=newFig(); hold on; changes=strings(0,1);
        for k=impact'
            [~,pk]=max(abs(D{k}.z(:,3)),[],'omitnan'); tpk=D{k}.t(pk); b=rmsBins(D{k}.t-tpk,D{k}.z(:,3));
            plot(b(:,1),b(:,2),'o-','DisplayName',M.test_id(k));
            pre=b(b(:,1)>=-5 & b(:,1)<-1,2); post=b(b(:,1)>1 & b(:,1)<=5,2);
            changes(end+1)=sprintf('%s: pre-window median RMS %.5g g, post-window %.5g g',M.test_id(k),median(pre,'omitnan'),median(post,'omitnan')); %#ok<AGROW>
        end
        xlabel('Time relative to largest observed residual [s]'); ylabel('1 s bin RMS [g]'); title('Impact-recording envelopes around observed maxima'); grid on; legend('Location','best');
        add(f,8,'impact_envelopes',impact,'One-second RMS envelopes aligned to each recording''s largest observed residual.',join(changes,'; '), ...
            'Alignment is a computed signal feature, not a known impact trigger. Pre/post summaries use -5 to -1 s and +1 to +5 s.', ...
            'No damping ratio or settling time is inferred because event timing, background forcing and missing intervals are insufficiently controlled.');
    end
end

%% 9. Comparative summary (three figures)
if ~isempty(combined)
    f=newFig(); tiledlayout(1,3); pos=[.25 .5 .75]; masses=unique(M.load_kg(combined)); pwms=unique(M.vibration_pwm(combined));
    for p=pos, nexttile; Z=nan(numel(masses),numel(pwms)); for a=1:numel(masses), for b=1:numel(pwms)
        ix=combined(M.load_kg(combined)==masses(a)&M.vibration_pwm(combined)==pwms(b)&M.load_position_norm(combined)==p);
        if ~isempty(ix), Z(a,b)=mean(M.rms_z_g(ix),'omitnan'); end
    end, end
        imagesc(Z); colorbar; xticks(1:numel(pwms)); xticklabels(string(pwms)); yticks(1:numel(masses)); yticklabels(string(masses)); xlabel('PWM'); ylabel('Applied mass [kg]'); title(positionName(p));
        clim([min(M.rms_z_g(combined)),max(M.rms_z_g(combined))]);
    end
    add(f,9,'combined_response_map',combined,'Same-batch map of mean dynamic z RMS [g] across mass, PWM and position.',metricRange(M.rms_z_g(combined),'Individual run RMS','g'), ...
        'Each cell is an equal-weight mean of run RMS values; common color scale across panels.', 'A descriptive operating-condition map is not a trained or validated digital twin.');
end
f=newFig(); tiledlayout(1,2); nexttile;
ix=find(isfinite(M.load_kg)&isfinite(M.vibration_pwm)&~ismember(M.category,["Wind","Impact"]));
scatter(M.load_kg(ix),M.vibration_pwm(ix),45,M.temp_left_mean_C(ix),'filled'); colorbar; xlabel('Applied mass [kg]'); ylabel('PWM'); title('Recorded left temperature [deg C]'); grid on;
nexttile; countBars(M.category,'Category','Recordings'); title('Experimental coverage');
add(f,9,'coverage_summary',allIdx,'Coverage of load, motor command and observed left temperature, plus recording counts.', ...
    sprintf('%d non-disturbance recordings have known mass and PWM; %d thermal segments have unspecified load/PWM.',numel(ix),numel(thermal)), ...
    'Coverage only; overlapping markers indicate repeated settings. Thermal segments are counted separately in the right panel.', 'Temperature was observed, not independently varied in a balanced factorial design. This plot does not compare response across incompatible batches.');
f=newFig(); tiledlayout(1,2); nexttile;
flag=find(M.lc_extreme_count>0); if ~isempty(flag), bar(M.lc_extreme_count(flag)); xticks(1:numel(flag)); xticklabels(M.test_id(flag)); xtickangle(30); else, bar(0); end
ylabel('Entries at/beyond 8,388,607 counts'); title('Retained load-cell extreme-value audit'); grid on;
nexttile; scatter(M.gap_count,M.min_coverage*100,30,'filled'); xlabel('Timestamp gaps > 1.5 median dt'); ylabel('Minimum finite channel coverage [%]'); title('Completeness and timing are distinct'); grid on;
add(f,9,'limitations_summary',allIdx,'Data-quality issues retained in the cleaned data and disclosed for interpretation.', ...
    sprintf('%d extreme load-cell entries occur in %d recordings; %d of %d recordings contain timing gaps.',sum(M.lc_extreme_count),nnz(M.lc_extreme_count),nnz(M.gap_count),n), ...
    '8,388,607 is used as an audit threshold motivated by the project''s HX711 acquisition code; no values are deleted.', ...
    'The extreme-value count is diagnostic, not a new QC classification. Existing QC reports remain unchanged.');

%% Manifest, report, portable archive, and hard validation
manifest=struct2table(P); writetable(manifest,fullfile(out,'plot_manifest.csv'));
writetable(M,fullfile(out,'run_metrics.csv'));
write_REPS_report(out,M,manifest,notes,thermalStats);
copyfile(fullfile(out,'plot_manifest.csv'),fullfile(out,'report','plot_manifest.csv'));
copyfile(fullfile(out,'run_metrics.csv'),fullfile(out,'report','dataset_index.csv'));
copyfile(fullfile(out,'frequency_audit.csv'),fullfile(out,'report','frequency_audit.csv'));
assert(height(manifest)==numel(unique(manifest.figure_filename)),'Duplicate figure filenames.');
for i=1:height(manifest)
    assert(isfile(fullfile(out,manifest.figure_filename(i))),'Missing exported figure.');
    assert(isfile(fullfile(out,'report','figures',manifest.report_filename(i))),'Missing report image.');
    assert(~excluded(manifest.source_cleaned_csv_files(i)),'Excluded source in plot manifest.');
end
tex=fileread(fullfile(out,'report','main.tex'));
refs=regexp(tex,'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}','tokens');
assert(numel(refs)==height(manifest),'Report and manifest figure counts differ.');
for j=1:numel(refs), assert(isfile(fullfile(out,'report',refs{j}{1})),'Broken LaTeX image reference.'); end
after=fingerprints(cleanRoot); assert(isequal(before,after),'Source dataset changed during analysis.');
writetable(after,fullfile(out,'validation','input_hashes_after.csv'));
validation=struct('matlab_version',version,'recordings',n,'figures',height(manifest), ...
    'scrapped_sources_in_analysis',0,'input_files_unchanged',true,'source_hash_count',height(before), ...
    'unique_figure_names',true,'all_source_files_exist',true,'all_latex_images_exist',true, ...
    'thermal_segments_separate',true,'accepted_spectral_intervals',nnz(M.spectral_eligible), ...
    'signal_processing_functions_available',logical(signalOK),'metadata_notes',notes);
fid=fopen(fullfile(out,'validation','validation.json'),'w'); fprintf(fid,'%s',jsonencode(validation,'PrettyPrint',true)); fclose(fid);
zipFiles=["main.tex";"plot_manifest.csv";"dataset_index.csv";"frequency_audit.csv";"figures/"+manifest.report_filename];
zip(fullfile(out,'REPS_DOT_Overleaf.zip'),cellstr(zipFiles),fullfile(out,'report'));
fprintf('SUCCESS: %d figures and a self-contained report generated. Source hashes unchanged.\n',height(manifest));

    function add(fig,cat,slug,idx,caption,findings,method,limitations)
        idx=unique(idx(:),'stable'); id=sprintf('F%02d',numel(P)+1);
        name=string(id)+"_"+string(slug)+".png";
        relative=fullfile('figures',cats(cat),name);
        exportgraphics(fig,fullfile(out,relative),'Resolution',300,'BackgroundColor','white');
        copyfile(fullfile(out,relative),fullfile(out,'report','figures',name)); close(fig);
        rec=struct('figure_id',string(id),'figure_filename',replace(string(relative),'\','/'), ...
            'category',cats(cat),'source_experiment_ids',join(M.test_id(idx),'; '), ...
            'source_cleaned_csv_files',join("cleaned_data/"+replace(M.cleaned_file(idx),'\','/'),'; '), ...
            'experimental_conditions',join(unique(conditionDescription(M,idx)),'; '), ...
            'analysis_method',string(method),'calculated_numerical_findings',string(findings), ...
            'limitations_or_warnings',string(limitations)+" "+common, ...
            'included_in_latex_report',true,'report_filename',name,'caption',string(caption), ...
            'source_count',numel(idx));
        assert(~ismissing(rec.experimental_conditions) && strlength(rec.experimental_conditions)>0,'Missing figure conditions.');
        P=[P;rec]; %#ok<AGROW>
        fprintf('%s %s\n',id,slug);
    end
end

function ensureDir(p)
if ~isfolder(p), mkdir(p); end
end

function yes=excluded(s)
s=lower(replace(string(s),'\','/'));
yes=contains('/'+s+'/','/9_4_26/')|contains('/'+s+'/','/911_data/');
end

function [M,notes]=loadMetadata(root)
F=readtable(fullfile(root,'ME2_master_features.csv'),'TextType','string');
Q=readtable(fullfile(root,'ME2_QC_report.csv'),'TextType','string');
F.source_subfolder(ismissing(F.source_subfolder))="";
F.test_condition(ismissing(F.test_condition))="";
Q.source_subfolder(ismissing(Q.source_subfolder))="";
F=F(~excluded(F.source_subfolder)&~excluded(F.filename),:);
notes=strings(0,1);
M=F(:,{'test_id','filename','source_subfolder','load_kg','load_position_norm','vibration_pwm','commanded_frequency_Hz','temperature_code','test_condition'});
M.cleaned_file=strings(height(M),1); M.qc_status=repmat("UNKNOWN",height(M),1); M.qc_notes=strings(height(M),1);
M.category=repmat("Unknown",height(M),1);
for i=1:height(M)
    [~,stem]=fileparts(M.filename(i)); stem=regexprep(string(stem),'\.csv$','');
    if startsWith(M.test_id(i),'THERMAL_01_PART')
        M.source_subfolder(i)="thermal_transient"; stem=M.test_id(i); M.category(i)="Thermal";
    elseif M.test_condition(i)=="WIND", M.category(i)="Wind";
    elseif M.test_condition(i)=="IMPACT", M.category(i)="Impact";
    elseif isfinite(M.commanded_frequency_Hz(i)), M.category(i)="Frequency sweep";
    elseif M.load_kg(i)>0 && M.vibration_pwm(i)>0, M.category(i)="Load + vibration";
    elseif M.load_kg(i)>0 && M.vibration_pwm(i)==0, M.category(i)="Static load";
    elseif M.load_kg(i)==0 && M.vibration_pwm(i)>0, M.category(i)="Vibration";
    elseif M.load_kg(i)==0 && M.vibration_pwm(i)==0, M.category(i)="Baseline";
    end
    M.cleaned_file(i)=string(fullfile(M.source_subfolder(i),stem+'_clean.csv'));
    q=find(Q.filename==F.filename(i)&Q.source_subfolder==F.source_subfolder(i));
    assert(numel(q)<=1,'Ambiguous QC join by source filename and batch.');
    if ~isempty(q), M.qc_status(i)=Q.qc_status(q); M.qc_notes(i)=Q.qc_notes(q); end
end
manifestPath=fullfile(root,'model_dataset','manifest.csv');
if isfile(manifestPath)
    V=readtable(manifestPath,'TextType','string');
    assert(all(ismember({'cleaned_file','source_file'},V.Properties.VariableNames)),'Manifest schema unsupported; refusing to infer paths.');
    banned=excluded(V.cleaned_file)|excluded(V.source_file);
    for i=1:height(M)
        q=find(replace(string(V.cleaned_file),'\','/')==replace(M.cleaned_file(i),'\','/'));
        assert(numel(q)==1,'Each cleaned file requires one manifest row.');
        assert(~banned(q),'Manifest source points to a scrapped batch.');
        for field=["load_kg","load_position_norm","vibration_pwm","commanded_frequency_Hz"]
            if ismember(field,string(V.Properties.VariableNames)), assert(isequaln(M.(field)(i),V.(field)(q)),'Conflicting manifest and feature metadata.'); end
        end
        if ismember('eligibility_status',V.Properties.VariableNames) && string(V.eligibility_status(q))=="EXCLUDE", M.qc_status(i)="FAIL"; end
    end
    notes(end+1)="Manifest was used to cross-check source provenance, conditions and exclusion flags.";
else
    notes(end+1)="cleaned_data/model_dataset/manifest.csv is absent. Provenance was reconstructed from the existing master feature table and unique batch/filename paths, with QC joined by batch plus filename. No replacement was written into cleaned_data.";
end
M=M(M.qc_status~="FAIL",:);
assert(~any(excluded(M.cleaned_file)),'Scrapped batch included.');
assert(numel(unique(M.cleaned_file))==height(M),'Cleaned paths are not unique.');
M.run_id=replace(M.cleaned_file,'\','/'); M=sortrows(M,'run_id');
for part=["THERMAL_01_PART1","THERMAL_01_PART2"]
    if ~any(M.test_id==part), notes(end+1)="Missing cleaned thermal segment: "+part+". Original Excel files were not read."; end
end
notes(end+1)="The existing cleaner defines time in seconds, acceleration in g, temperature in deg C, and load-cell output as uncalibrated raw counts. Metadata maps L01/L02/L03 to 0.25/0.5/1 kg and V01/V02/V03 to PWM 64/128/192.";
end

function H=fingerprints(root)
files=dir(fullfile(root,'**','*')); files=files(~[files.isdir]); paths=strings(numel(files),1); hashes=paths;
for i=1:numel(files)
    p=fullfile(files(i).folder,files(i).name); paths(i)=extractAfter(string(p),strlength(string(root))+1);
    fid=fopen(p,'rb'); assert(fid>=0); guard=onCleanup(@() fclose(fid));
    md=java.security.MessageDigest.getInstance('SHA-256');
    while ~feof(fid), bytes=fread(fid,1048576,'*uint8'); md.update(bytes); end
    hashes(i)=lower(join(string(dec2hex(typecast(md.digest(),'uint8'),2)),'')); clear guard;
end
H=sortrows(table(paths,hashes,'VariableNames',{'relative_path','sha256'}),'relative_path');
end

function y=linearResidual(t,x)
y=nan(size(x)); ok=isfinite(t)&isfinite(x);
if nnz(ok)<3 || max(t(ok))-min(t(ok))<=0, return; end
u=t(ok)-mean(t(ok)); G=[ones(nnz(ok),1),u]; y(ok)=x(ok)-G*(G\x(ok));
end

function [s,reason]=spectralSegment(t,z,toolboxOK)
dt=diff(t); md=median(dt(dt>0)); valid=isfinite(z)&isfinite(t);
split=[true;dt<=0 | dt>1.5*md | ~valid(1:end-1) | ~valid(2:end)];
a=find(split); b=[a(2:end)-1;numel(t)]; durations=t(b)-t(a); durations(~valid(a))=-Inf;
[len,j]=max(durations); if ~isfinite(len), len=0; j=1; end
ix=a(j):b(j); tt=t(ix); zz=z(ix); localdt=diff(tt);
s=struct('valid',false,'duration',len,'fs',NaN,'start',tt(1),'stop',tt(end),'jitter',NaN);
if numel(tt)>1, s.fs=1/median(localdt); s.jitter=max(abs(localdt-median(localdt)))/median(localdt); end
if any(dt<=0), reason="Nonincreasing timestamps"; return; end
if len<4 || numel(ix)<256, reason="Continuous interval below 4 s / 256 samples"; return; end
if s.jitter>.20, reason="Within-interval jitter exceeds 20 percent"; return; end
if ~toolboxOK, reason="Signal Processing Toolbox unavailable"; return; end
% No gap > 1.5 median dt enters this interval. No extrapolation or zero fill.
grid=(tt(1):1/s.fs:tt(end))'; x=interp1(tt,zz,grid,'linear');
assert(all(isfinite(x)),'Unexpected interpolation failure.'); x=detrend(x,1);
N=numel(x); w=hann(N,'periodic'); Y=abs(fft(x.*w))/sum(w); L=floor(N/2)+1;
s.amplitude=Y(1:L); if rem(N,2)==0, s.amplitude(2:end-1)=2*s.amplitude(2:end-1); else, s.amplitude(2:end)=2*s.amplitude(2:end); end
s.f=(0:L-1)'*s.fs/N; band=s.f>=.5 & s.f<=min(40,.4*s.fs); indices=find(band);
[s.peakAmplitude,k]=max(s.amplitude(band)); s.peakHz=s.f(indices(k));
win=min(N,round(2*s.fs)); win=max(16,win); overlap=floor(win/2);
[s.psd,s.pf]=pwelch(x,hann(win,'periodic'),overlap,win,s.fs,'onesided');
[~,s.sf,s.st,s.sp]=spectrogram(x,hann(win,'periodic'),overlap,win,s.fs,'yaxis');
s.valid=true; reason="Accepted: linear jitter resampling";
end

function f=newFig()
f=figure('Visible','off','Color','w','Position',[40 40 1200 720]);
end

function countBars(labels,xlab,ylab)
labels=string(labels); labels(ismissing(labels)|strlength(labels)==0)="Unknown";
[u,~,g]=unique(labels,'stable'); counts=accumarray(g,1); bar(counts); xticks(1:numel(u)); xticklabels(u); xtickangle(25);
xlabel(xlab); ylabel(ylab); grid on; for k=1:numel(u), text(k,counts(k)," "+counts(k),'HorizontalAlignment','center','VerticalAlignment','bottom'); end
ylim([0 max(counts)*1.18+1]);
end

function labels=numberLabels(x,suffix)
labels=string(x)+suffix; labels(~isfinite(x))="Unknown";
end

function y=shortBatch(x)
y=replace(x,["918 load variation","918 vibration variation","9_25_loadvib","10_9_Wind&Impact","thermal_transient","918_freq"], ...
    ["Sep 18 / static","Sep 18 / vibration","Sep 25 / load + vibration","Oct 9 / disturbance","Thermal session","Sep 18 / frequency"]);
end

function s=side(j)
names=["Left","Right"]; s=names(j);
end
function s=side3(j)
names=["Left","Center","Right"]; s=names(j);
end
function s=choose(j,a,b)
if j==1, s=a; else, s=b; end
end
function name=positionName(p)
name="Unknown"; if p==.25, name="Left"; elseif p==.5, name="Center"; elseif p==.75, name="Right"; end
end
function positionAxis()
xticks([.25 .5 .75]); xticklabels({'Left','Center','Right'}); xlim([.15 .85]); xlabel('Loading position');
end
function s=labelRun(M,k)
s=M.test_id(k)+" | "+string(M.load_kg(k))+" kg | "+positionName(M.load_position_norm(k))+" | PWM "+string(M.vibration_pwm(k));
end

function plotGap(t,y,md,label)
% Insert NaN vertices, preserving every original point and its amplitude.
g=find(diff(t)>1.5*md | diff(t)<=0); tt=nan(numel(t)+numel(g),1); yy=tt;
indices=(1:numel(t))'+[0;cumsum(diff(t)>1.5*md | diff(t)<=0)];
tt(indices)=t; yy(indices)=y; plot(tt,yy,'DisplayName',label);
end

function reps=representatives(ix,group,metric,M)
keys=string(group(ix)); keys(ismissing(keys))="Unknown"; u=unique(keys,'stable'); reps=zeros(0,1);
for g=u'
    candidates=ix(keys==g); values=metric(candidates); ok=isfinite(values); candidates=candidates(ok); values=values(ok);
    if isempty(candidates), continue; end
    [~,order]=sort(M.run_id(candidates)); candidates=candidates(order); values=values(order);
    [~,j]=min(abs(values-median(values))); reps(end+1,1)=candidates(j); %#ok<AGROW>
end
end

function groupResponse(M,ix,xname,yname,groupvars)
hold on; if isempty(ix), return; end
[~,order]=sortrows(M(ix,:),cellstr(groupvars)); ix=ix(order);
key=strings(numel(ix),1); groupvars=string(groupvars);
for v=groupvars
    if v=="source_subfolder"
        values=replace(M.(v)(ix),["918 load variation","918 vibration variation","9_25_loadvib"],["Sep 18","Sep 18","Sep 25"]);
    elseif v=="load_position_norm"
        values=strings(numel(ix),1); for p=1:numel(ix), values(p)=positionName(M.(v)(ix(p))); end
    elseif v=="load_kg", values=string(M.(v)(ix))+" kg";
    elseif v=="vibration_pwm", values="PWM "+string(M.(v)(ix));
    else, values=v+"="+string(M.(v)(ix)); end
    key=key+values+" ";
end
u=unique(key,'stable'); markers={'o','s','^','d','v','>'};
for j=1:numel(u)
    ids=ix(key==u(j)); xx=unique(M.(xname)(ids)); xx=xx(isfinite(xx)); mu=nan(size(xx)); sd=mu; nn=zeros(size(xx));
    for k=1:numel(xx), y=M.(yname)(ids(M.(xname)(ids)==xx(k))); y=y(isfinite(y)); nn(k)=numel(y); mu(k)=mean(y); if numel(y)>1, sd(k)=std(y); end, end
    errorbar(xx,mu,sd,markers{1+mod(j-1,numel(markers))},'LineStyle','none','MarkerSize',6, ...
        'DisplayName',strtrim(u(j))+" [n="+join(string(nn'),',')+"]");
end
grid on; legend('Location','best','FontSize',9); ax=gca; ax.YAxis.Exponent=0;
if max(abs(M.(yname)(ix)),[],'omitnan')<1, ytickformat('%.4f'); else, ytickformat('%.4g'); end
x=M.(xname)(ix); x=x(isfinite(x)); if ~isempty(x), pad=max((max(x)-min(x))*.08,.025); xlim([min(x)-pad,max(x)+pad]); end
end

function key=conditionKey(M,ix)
% MATLAB string(NaN) is <missing>, which would erase a concatenated key.
% Explicit labels are essential for correct grouping and traceability.
disturbance=M.test_condition(ix); disturbance(ismissing(disturbance)|strlength(disturbance)==0)="none labelled";
temp=M.temperature_code(ix); temp(ismissing(temp)|strlength(temp)==0)="unknown";
key=M.source_subfolder(ix)+" | m="+numberLabels(M.load_kg(ix),' kg')+ ...
    " | position="+numberLabels(M.load_position_norm(ix),'')+ ...
    " | PWM="+numberLabels(M.vibration_pwm(ix),'')+ ...
    " | command="+numberLabels(M.commanded_frequency_Hz(ix),' Hz')+ ...
    " | temperature code="+temp+" | disturbance="+disturbance;
end
function desc=conditionDescription(M,ix)
desc=conditionKey(M,ix)+"; QC="+M.qc_status(ix);
end

function repeatabilityPlot(M,ix)
key=conditionKey(M,ix); [u,~,g]=unique(key,'stable'); hold on;
scatter(g-.08,M.lc_left_median(ix),40,'filled','DisplayName','Left'); scatter(g+.08,M.lc_right_median(ix),40,'filled','DisplayName','Right');
labels=strings(numel(u),1); for j=1:numel(u), k=ix(find(g==j,1)); labels(j)=shortBatch(M.source_subfolder(k))+" / "+M.load_kg(k)+" kg / "+positionName(M.load_position_norm(k)); end
xticks(1:numel(u)); xticklabels(labels); xtickangle(25); ylabel('Run median [counts]'); legend('Location','best'); grid on;
end

function s=metricRange(x,label,units)
x=x(isfinite(x)); if isempty(x), s=string(label)+": no finite values."; else, s=sprintf('%s range %.6g--%.6g %s (n=%d).',label,min(x),max(x),units,numel(x)); end
end
function s=matchedChange(M,ix)
s=strings(0,1); for p=[.25 .5 .75]
    off=ix(M.load_position_norm(ix)==p&M.vibration_pwm(ix)==0); on=ix(M.load_position_norm(ix)==p&M.vibration_pwm(ix)==192);
    if ~isempty(off)&&~isempty(on), a=mean(M.rms_z_g(off)); b=mean(M.rms_z_g(on)); if a>0, s(end+1)=sprintf('%s: mean RMS %.5g g at PWM 0 and %.5g g at PWM 192 (%+.2f percent)',positionName(p),a,b,100*(b-a)/a); end, end %#ok<AGROW>
end
s=join(s,'; ');
end
function s=spectralDescription(M,ix)
s="Accepted continuous interval only; linear interpolation at median-dt rate with no extrapolation; linear detrend; periodic Hann window; coherent-gain-corrected one-sided FFT; Welch/spectrogram use 2 s Hann windows and 50 percent overlap. ";
for k=ix', s=s+sprintf('%s: %.3f--%.3f s, fs=%.6g Hz, max dt jitter=%.3g. ',M.test_id(k),M.spectral_start_s(k),M.spectral_end_s(k),M.spectral_fs_Hz(k),M.spectral_jitter_fraction(k)); end
end

function b=thermalBins(T)
names={'accel_x_g','accel_y_g','accel_z_g','temp_left_C','temp_center_C','temp_right_C','loadcell_left_raw','loadcell_right_raw'};
valid=any(isfinite(T{:,names}),2)&isfinite(T.time_s); t=T.time_s(valid); X=T{valid,names};
g=floor(t-min(t)); bins=unique(g); Y=nan(numel(bins),numel(names));
% Paired-bin medians use the same finite rows for temperature and sensor.
for i=1:numel(bins), for j=1:numel(names)
    rows=g==bins(i)&isfinite(X(:,j))&isfinite(X(:,4)); Y(i,j)=median(X(rows,j),'omitnan');
end, end
b=array2table([bins,Y],'VariableNames',[{'time_s'},names]);
end
function [slope,r2]=scatterFit(x,y)
ok=isfinite(x)&isfinite(y); x=x(ok); y=y(ok); scatter(x,y,12,'filled','MarkerFaceAlpha',.45); hold on; grid on;
slope=NaN; r2=NaN;
if numel(x)>=20 && max(x)-min(x)>=1
    G=[ones(size(x)),x-mean(x)]; coeff=G\y; slope=coeff(2); fit=G*coeff;
    if sum((y-mean(y)).^2)>0, r2=1-sum((y-fit).^2)/sum((y-mean(y)).^2); end
    lim=[min(x),max(x)]; plot(lim,coeff(1)+coeff(2)*(lim-mean(x)),'k-','LineWidth',1.5);
    text(.03,.94,sprintf('slope %.3g; R^2 %.3f',slope,r2),'Units','normalized','VerticalAlignment','top','BackgroundColor','white');
else
    text(.03,.94,'Insufficient temperature span for fit','Units','normalized','VerticalAlignment','top');
end
end
function s=thermalRanges(D,ix)
s=strings(0,1); for k=ix', X=D{k}.T{:,{'temp_left_C','temp_center_C','temp_right_C'}}; s(end+1)=sprintf('Segment %d temperature range %.3f--%.3f deg C',numel(s)+1,min(X,[],'all','omitnan'),max(X,[],'all','omitnan')); end %#ok<AGROW>
s=join(s,'; ');
end
function s=driftSummary(B,ix)
s=strings(0,1); for k=ix', b=B{k}; y=b{:,{'loadcell_left_raw','loadcell_right_raw'}}; d=median(y(b.time_s>=max(b.time_s)-5,:),1,'omitnan')-median(y(b.time_s<=min(b.time_s)+5,:),1,'omitnan'); s(end+1)=sprintf('Segment %d final-minus-initial 5 s medians: left %.5g, right %.5g counts',numel(s)+1,d(1),d(2)); end %#ok<AGROW>
s=join(s,'; ');
end
function b=rmsBins(t,z)
ok=isfinite(t)&isfinite(z); t=t(ok); z=z(ok); g=floor(t); u=unique(g); b=nan(numel(u),2);
for j=1:numel(u), b(j,:)=[u(j)+.5,sqrt(mean(z(g==u(j)).^2))]; end
end
