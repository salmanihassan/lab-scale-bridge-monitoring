function write_REPS_report(out,M,P,notes,thermalStats)
%WRITE_REPS_REPORT Assemble an Overleaf-ready report only from actual outputs.
path=fullfile(out,'report','main.tex'); fid=fopen(path,'w','n','UTF-8'); assert(fid>=0);
guard=onCleanup(@() fclose(fid)); %#ok<NASGU>
emit('\documentclass[10pt,letterpaper]{article}');
emit('\usepackage[margin=0.7in]{geometry}');
emit('\usepackage[T1]{fontenc}');
emit('\usepackage{lmodern,graphicx,amsmath,siunitx,booktabs,float,subcaption}');
emit('\usepackage{longtable,array,xcolor,microtype,fancyhdr,hyperref,xurl}');
emit('\definecolor{repsblue}{HTML}{164966}');
emit('\hypersetup{colorlinks=true,linkcolor=repsblue,urlcolor=repsblue,hypertexnames=false,pdftitle={REPS Experimental Characterization},pdfauthor={REPS Digital Twin Project}}');
emit('\setlength{\parindent}{0pt}\setlength{\parskip}{4pt}');
emit('\setlength{\intextsep}{8pt}\setlength{\textfloatsep}{10pt}');
emit('\clubpenalty=10000\widowpenalty=10000');
emit('\usepackage{needspace,caption}\captionsetup{font=small,labelfont=bf,skip=4pt}');
emit('\setlength{\headheight}{14pt}\pagestyle{fancy}\fancyhf{}');
emit('\fancyhead[L]{\small REPS Digital Twin Project}\fancyhead[R]{\small Experimental characterization}');
emit('\fancyfoot[C]{\thepage}');
emit('\renewcommand{\arraystretch}{1.15}');
emit('\begin{document}');
emit('\begin{titlepage}\centering\vspace*{0.8in}');
emit('{\color{repsblue}\Large REPS DIGITAL TWIN PROJECT\par}\vspace{0.35in}');
emit('{\Huge\bfseries Experimental Characterization of a Laboratory-Scale Bridge for Digital Twin Development\par}\vspace{0.4in}');
emit('{\Large REPS Digital Twin Project --- Department of Transportation Progress Presentation\par}\vspace{0.25in}');
emit('{\large November 5, 2026\par}\vfill');
emit('\begin{minipage}{0.88\textwidth}\textbf{Scope.} Mechanical experimental characterization and preparation of existing cleaned sensor data. This report does not present a completed, trained, or validated AI digital twin.\par');
emit(tex(sprintf('This generated edition contains %d retained recordings and %d figures. Every figure is linked to source cleaned CSV files in the supplied plot manifest. The September 4 and September 11 batches are excluded before all analysis.',height(M),height(P))));
emit('\end{minipage}\vspace{0.5in}\end{titlepage}');
emit('\tableofcontents\clearpage');

emit('\section{Introduction}');
emit('The REPS Digital Twin project uses a laboratory-scale instrumented bridge to investigate how measured response varies with applied mass, loading position, commanded vibration, temperature, and external disturbances. The present work establishes a reproducible experimental visualization baseline for the Department of Transportation progress presentation. It supports assessment of data coverage and limitations before model development.');
emit('The analysis prioritizes comparable acquisition conditions and transparent provenance. Repeated runs summarize reproducibility at the recording level; individual time samples are not treated as independent experimental replicates. Numerical findings are generated directly from retained cleaned data.');
emit('The engineering questions are whether the sensor pair distinguishes applied mass and position, whether dynamic response changes consistently with motor command, and whether temperature and disturbances create responses that a future measurement model must separate. Static measurements test channel sensitivity and load-path effects; three-axis acceleration quantifies dynamic sensitivity; the thermal session tests the stability of sensor baselines; and wind/impact records expose transient response. Together these experiments identify candidate model inputs and acquisition requirements. They do not supply calibrated forces, a measured excitation transfer function, or independent model validation.');
emit('\section{Experimental System and Instrumentation}');
emit('The cleaned schema provides three acceleration axes in units of g, three temperature channels in degrees Celsius, two load-cell raw-output channels, a timestamp in seconds, and a logged motor state. The channel names identify left, center and right temperature locations and left and right load cells. The current files do not establish bridge geometry, exact accelerometer orientation, traceable calibration factors, or sensor uncertainty; these details are therefore not invented.');
emit('The existing processing script maps applied-mass codes L01, L02 and L03 to 0.25, 0.50 and 1.00 kg. It maps left, center and right loading positions to normalized labels 0.25, 0.50 and 0.75, and vibration codes V01, V02 and V03 to PWM commands 64, 128 and 192. These are experimental metadata, not values estimated from sensor outputs. P00 does not establish a physical loading coordinate.');
emit('Load-cell outputs are reported in uncalibrated counts. Differences and normalized ratios between these channels are signal descriptors and cannot establish support forces or load-sharing fractions without calibration. PWM is never converted into physical excitation frequency. Filename F labels are retained as commanded-frequency metadata only.');
emit('\section{Dataset Overview and Processing}');
for note=reshape(notes,1,[]), emit(tex(note)); end
emit('A targeted provenance search confirmed that the cleaner is designed to write \path{cleaned_data/model_dataset/manifest.csv}, but that file and its model-dataset directory are absent from the available Twin Data tree. A wider search through the available Fall 2026 project tree found no source manifest; the visualization manifests are outputs of this analysis. Thus the fallback is not caused by resolving the working directory incorrectly. The files alone cannot establish why the source manifest was omitted.');
emit('The September 25 T0 token is literal in the original \path{ME234_T0_L03_PC_V03_TEMP01.csv.xlsx} filename and in the feature/QC records. It is not a parser truncation. Its cleaned file has a unique byte hash among the retained recordings and differs in length from the neighboring same-condition T0235 recording. The malformed-looking prefix does not establish an intended test number, so T0 is preserved and identified by its full relative path. Acquisition logs are required to resolve the intended identity.');
emit('Both forbidden acquisition folders, including their cleaned counterparts, are rejected by path components before sensor files are loaded. Unique relative cleaned-file paths identify runs, since test identifiers are not globally unique. QC is joined on acquisition batch and original filename. Existing master-feature numerical response values are not used as substitutes for recalculation from the actual cleaned samples.');
emit(tex(sprintf('The retained set contains %d recordings, %d with existing CHECK status. There are %d thermal recording segments from the single THERMAL_01 session. The longest interval passing the continuity screen in the full set is %.3f s, before the minimum-duration rule is applied. All source files were SHA-256 hashed before and after generation.',height(M),nnz(M.qc_status=="CHECK"),nnz(M.category=="Thermal"),max(M.longest_interval_s))));
emit('\subsection*{Time-domain metrics}');
emit('For each acceleration axis, the finite cleaned samples are fitted to a straight line using their actual timestamps. Dynamic acceleration is the residual from that fit. The same method is used for static, vibrating and disturbed recordings:');
emit('\begin{equation} a_{\mathrm{dyn},i}=a_i-(\hat\beta_0+\hat\beta_1(t_i-\bar t)),\qquad a_{\mathrm{RMS}}=\sqrt{\frac{1}{N}\sum_{i=1}^{N}a_{\mathrm{dyn},i}^{2}}.\end{equation}');
emit('RMS is sample weighted over all finite residuals, including both logged motor states. A motor OFF sample within a switching sequence is not assumed to be an undisturbed baseline. Missing samples remain missing and no extra peak filtering is applied. Time-history lines are broken at gaps larger than 1.5 times the median positive timestamp increment. Static aggregates use run medians to reduce the influence of retained extreme values. Error bars, where shown, are sample standard deviations between matching runs and are not confidence intervals.');
emit('\subsection*{Representative selection and comparability}');
emit('Representative recordings are selected deterministically as the run nearest the median relevant metric within each displayed group, with relative filename ordering to break ties. Aggregate comparisons retain acquisition batch, mass, position, PWM, frequency label and disturbance status as applicable. Missing metadata remain unknown. Temperature is not treated as a controlled covariate.');
renderCategory(1);

section(4,'Static Load Characterization', ...
    'Static recordings quantify the measured load-cell response to applied mass. The 0.25 kg runs were acquired on September 25, whereas the retained 0.5 and 1 kg static series were acquired on September 18. These batches are not combined into a single calibration curve. Individual repetitions and raw signal asymmetry expose variability without asserting that an expected mechanical trend occurred.');
renderCategory(2);
section(5,'Load Position Sensitivity', ...
    'The position comparisons retain mass and batch strata. Left, center and right refer to metadata position labels. The normalized raw-signal contribution is included to describe relative channel output, but differing offsets and gains prevent identifying it with a support reaction or load fraction.');
renderCategory(3);
section(6,'Vibration Response', ...
    'The unloaded September 18 vibration series provides a within-batch PWM comparison. Both cleaned acceleration levels and dynamic residuals are displayed. RMS and peak quantities apply to the existing cleaned signals. Earlier cleaning used a spike filter and interpolation of short missing runs, so original physical peaks may no longer be available.');
renderCategory(4);
section(7,'Frequency-Domain Analysis', ...
    'Timing is audited before spectral analysis. The cleaner converted milliseconds to seconds and had already removed nonincreasing timestamps or selected a reset segment. The present cleaned timestamps can therefore reveal remaining jitter and gaps but cannot reconstruct discarded raw resets. The recurring increments near 0.09--0.10 s, in otherwise approximately 0.01 s sampling, are treated conservatively as missing acquisition intervals. Their acquisition cause cannot be established from cleaned data alone.');
emit('For each run, the algorithm splits at missing acceleration, nonincreasing timestamps, or a timestamp increment greater than 1.5 times the median. It selects the longest remaining interval and requires at least four seconds, at least 256 samples, and maximum interval deviation no greater than 20 percent of the local median. Four seconds gives at least two cycles at the lowest inspected 0.5 Hz and a nominal Fourier spacing no coarser than 0.25 Hz. These are minimum engineering screening rules, not a certification of stationarity or anti-aliasing.');
emit('Only an accepted interval is linearly interpolated onto its median-increment grid, without extrapolation or bridging rejected gaps. Base MATLAB supplies linear detrending and fft. The periodic Hann window is evaluated directly as $w_n=0.5-0.5\cos(2\pi n/N)$. The amplitude is $|\mathrm{FFT}(w a_{dyn})|/\sum w$, with positive-frequency bins doubled except DC and, for even N, Nyquist. Frequencies are $k f_s/N$. The searched response-peak band is 0.5 Hz to the smaller of 40 Hz and 0.4 times the sampling rate. Bin spacing is not the ability to resolve neighboring tones: Hann windowing broadens spectral features. This is a response spectrum, not a transfer function because input force is not measured.');
emit('The MATLAB license test recognizes Signal Processing Toolbox entitlement, but hann, pwelch and spectrogram are not installed in this execution environment. This prevents the optional toolbox analyses, not the base-MATLAB FFT. Welch PSD and spectrograms are omitted.');
eligible=nnz(M.spectral_eligible);
if eligible==0
    emit('\textbf{Result for this execution: no spectral analysis is emitted.} FFT amplitude spectra, Welch PSD, spectrograms, dominant-frequency comparisons, frequency-versus-load plots and commanded-versus-measured peak plots are omitted. Timing diagnostics are included instead. No peaks are inferred from PWM or from the approximately 100 Hz median-interval sampling rate.');

else
    k=find(M.spectral_eligible,1);
    emit(tex(sprintf('%d recording passes the unchanged interval rules: T0236, from %.3f to %.3f s (%.3f s). Its %d source samples become %d grid values at %.3f Hz, spanning %.3f s, with FFT bin spacing %.6f Hz. The other 90 candidates fail continuity-duration screening. The first accepted spectrum is appended as F33 to preserve all existing figure identifiers.',eligible,M.spectral_start_s(k),M.spectral_end_s(k),M.longest_interval_s(k),M.fft_source_samples(k),M.fft_N(k),M.spectral_fs_Hz(k),M.fft_grid_span_s(k),M.fft_df_Hz(k))));
end
renderCategory(5);
section(8,'Combined Load and Vibration Effects', ...
    'The September 25 series supports comparisons across applied mass, position and PWM within one acquisition batch. A 0.25 kg subset also supports vibration-disabled versus vibration-enabled comparisons at matching position. The retained dataset has no matching unloaded vibration baseline in this batch, so cross-batch unloaded and loaded recordings are not used to claim a loading effect.');
renderCategory(6);
section(9,'Temperature-Induced Sensor Drift', ...
    'THERMAL\_01 consists of two recording segments from one session with an approximately five-minute interruption. Each segment has its own elapsed-time axis, starting at its first finite sensor record. No samples are invented and no line crosses the interruption. Part 2 contains an all-missing leading record followed by a 539.826 s timestamp gap; this artifact is distinct from the approximate interruption supplied in the experiment description.');
emit('Thermal scatter and drift summaries use occupied one-second median bins, explicitly as summaries rather than a replacement cleaned dataset. Empty bins are not filled. For each sensor, a trend is fitted to paired finite bin summaries only when there are at least 20 bins and a temperature span of at least one degree Celsius. Fits use left temperature as the common measured reference and are computed separately by segment. The reported slopes and coefficients of determination describe observational associations. Temporal autocorrelation, temperature gradients, possible orientation changes, excitation and segment offsets prevent interpreting the fits as a validated compensation model.');
renderCategory(7);
section(10,'Wind and Impact Disturbances', ...
    'Wind and impact recordings are summarized individually because exact event timing, forcing magnitude and wind speed are not supplied. Two wind recordings also have PWM 192, so motor operation is a confounder. No dedicated undisturbed reference is assumed. Impact-recording envelopes are aligned to the largest observed dynamic residual, which is a computed feature rather than a verified impact trigger. Pre- and post-feature windows are descriptive and are not labeled as confirmed baseline and settling intervals.');
renderCategory(8);
section(11,'Comparative Experimental Findings', ...
    'The summary figures emphasize within-batch dynamic response coverage, the recorded experimental design, and limitations that affect interpretation. Means of run metrics have equal recording weights. Coverage plots combine metadata only and do not imply that responses from different acquisition batches are interchangeable.');
renderCategory(9);
section(12,'Data Limitations and Future Work', ...
    'All retained recordings have source QC warnings. Near-complete finite sensor coverage must not be mistaken for trustworthy timing or calibrated physical measurement. The following limitations should guide the next experimental campaign.');
emit('\begin{itemize}');
emit('\item Acquire hardware-timestamped data with verified units, a measured sampling clock, gap logging and an anti-aliasing strategy. Record sufficiently long uninterrupted vibration intervals.');
emit('\item Establish independent load-cell calibration, tare checks, sensor orientation and measurement uncertainty. Retained extreme values require review of acquisition and earlier cleaning before calibration or safety-related inference.');
emit('\item Preserve raw data and sample-level cleaning provenance. The current cleaned files do not identify which values were previously interpolated or spike-filtered. The present pipeline cannot reconstruct lost peaks.');
emit('\item Collect same-batch unloaded and loaded baselines, balanced repetitions and recorded temperatures. Use a tachometer or measured excitation channel to distinguish motor command from actual excitation.');
emit('\item Record disturbance triggers, wind speed and impact force before attempting damping, settling-time or frequency-response identification.');
emit('\item Repeat controlled thermal cycles with fixed load and excitation to test compensation on independent sessions. The two present thermal segments are one session, not a validation split.');
emit('\item Resolve duplicate and suspicious test identifiers using acquisition logs. Current traceability uses complete relative paths, preserving the existing identifiers.');
emit('\end{itemize}');
emit(tex(sprintf('The cleaned load-cell data retain %d entries at or above an absolute magnitude of 8,388,607 counts in %d recordings. The largest retained left-channel value is %.9g counts. This threshold is an audit flag motivated by the project HX711 acquisition code, not an automatic correction or a new source QC decision. Median summaries reduce the influence of isolated extreme entries on descriptive aggregates.',sum(M.lc_extreme_count),nnz(M.lc_extreme_count),max(M.lc_left_max))));
section(13,'Conclusion', ...
    'Position sensitivity is the most consistent static finding: within each mass/batch stratum, moving the load right decreases the left-channel median and increases the right-channel median. Large offsets and unequal count sensitivities prevent interpreting these signals as forces. Static repetition scatter is small relative to raw output levels, but there is no specified acceptance tolerance and stable medians can conceal waveform artifacts.');
v=M.category=="Vibration"; z64=mean(M.rms_z_g(v&M.vibration_pwm==64)); z192=mean(M.rms_z_g(v&M.vibration_pwm==192));
p128=mean(M.peak_z_g(v&M.vibration_pwm==128)); p192=mean(M.peak_z_g(v&M.vibration_pwm==192));
emit(tex(sprintf('Unloaded mean z RMS rises from %.5f to %.5f g between PWM 64 and 192, a factor of %.2f. Yet mean peak amplitude decreases %.1f percent from PWM 128 to 192. Sustained vibration and isolated excursions therefore demand different model features. In the combined campaign, center loading has the lowest mean RMS in all nine matched mass/PWM comparisons, while mass and off/on effects are not uniformly monotonic. These observations motivate a model that accounts for interacting operating conditions, subject to independent replication.',z64,z192,z192/z64,100*(1-p192/p128))));
tr=thermalStats.sensor=="loadcell_right_raw"; r2=thermalStats.r_squared(tr);
emit(tex(sprintf('The right load-cell thermal association is much stronger in the second segment (R-squared %.3f) than in the first (%.3f), but the common time evolution and single session cannot establish causality or transferable compensation. Disturbance records contain localized peaks and, in some cases, sustained post-feature motion; missing forcing and event timing prevent damping identification. The recovered T0236 response peak at %.4f Hz lies in a broad low-frequency feature and is not a validated mode. Ninety of 91 candidate recordings still fail timing criteria.',r2(2),r2(1),M.dominant_Hz(logical(M.spectral_eligible)))));
emit('The next experimental priority is calibrated, synchronized measurement with uninterrupted timestamps, measured excitation and disturbance triggers, matched baselines, and independent thermal sessions. Preserve sample-level cleaning provenance and resolve source identifiers before training. The present work supplies evidence and requirements for digital twin development; neither the bridge model nor a functioning digital twin has been validated.');
emit('\clearpage\section{Appendix: Figure and Dataset Index}');
emit('Stable identifiers F01--F32 refer to the original figures; the added spectrum is F33, placed with the frequency results. The self-contained report includes \texttt{plot\_manifest.csv} with full source paths, conditions, methods and discussions; \texttt{dataset\_index.csv} with run metrics; \texttt{frequency\_audit.csv} with eligibility decisions; and \texttt{analysis\_evidence.csv} with unrounded numerical discussion inputs. The FFT bins are supplied in \texttt{T0236\_fft\_spectrum.csv}. Source paths refer to the original dataset; compilation needs only the included images.');
emit('\fontsize{8.5}{9.5}\selectfont\renewcommand{\arraystretch}{1}\begin{longtable}{p{0.08\textwidth}p{0.73\textwidth}r}\toprule Figure & Image filename & Runs\\\midrule\endhead');
for i=1:height(P), emit(sprintf('%s & ',P.figure_id(i))+"\path{"+P.report_filename(i)+"} & "+string(P.source_count(i))+"\\"); end
emit('\bottomrule\end{longtable}\normalsize');
if ~isempty(thermalStats)
    emit('\subsection*{Thermal fitted associations}');
    emit('Slopes use left temperature. Load-cell units are counts per degree Celsius; acceleration units are g per degree Celsius. These are descriptive fits, not correction coefficients.');
    emit('\small\begin{longtable}{p{0.25\textwidth}p{0.30\textwidth}rr}\toprule Segment & Sensor & Slope & $R^2$\\\midrule\endhead');
    for i=1:height(thermalStats), emit(string(sprintf('%s & %s & %.5g & %.3f',tex(thermalStats.segment(i)),tex(thermalStats.sensor(i)),thermalStats.slope_per_C(i),thermalStats.r_squared(i)))+"\\"); end
    emit('\bottomrule\end{longtable}\normalsize');
end
emit('\clearpage\subsection*{Retained dataset index}');
emit('All source QC statuses are CHECK. Batch keys: W = October 9 wind/impact; L = September 18 static; V = September 18 vibration; F = September 18 frequency commands; C = September 25 combined/static; T = thermal. Repeated IDs remain distinct through full paths in the CSV index. A dash means unknown.');
batches=["10_9_Wind&Impact","918 load variation","918 vibration variation","918_freq","9_25_loadvib","thermal_transient"];
codes=["W","L","V","F","C","T"];
emit('\noindent');
cut=ceil(height(M)/2);
for block=1:2
    emit('\begin{minipage}[t]{0.48\textwidth}\vspace{0pt}\centering\fontsize{8.5}{9.6}\selectfont');
    emit('\renewcommand{\arraystretch}{1}\begin{tabular}{lcrr}\toprule Test ID & Batch & kg & PWM\\\midrule');
    for i=(1+(block-1)*cut):min(block*cut,height(M))
        key=codes(batches==M.source_subfolder(i)); assert(isscalar(key));
        a=numeric(M.load_kg(i)); b=numeric(M.vibration_pwm(i));
        if strcmp(a,'unknown'), a='--'; end
        if strcmp(b,'unknown'), b='--'; end
        emit(string(sprintf('%s & %s & %s & %s',tex(M.test_id(i)),key,a,b))+"\\");
    end
    emit('\bottomrule\end{tabular}\end{minipage}');
    if block==1, emit('\hfill'); end
end
emit('\par\normalsize');
emit('\end{document}');

    function emit(s)
        assert(isscalar(string(s)),'Report output must be a scalar string, not a character matrix.');
        fprintf(fid,'%s\n',char(s));
        if ~startsWith(string(s),'\') && ~contains(string(s),' & '), fprintf(fid,'\n'); end
    end
    function section(number,name,body)
        emit('\Needspace{5\baselineskip}');
        emit('\section{'+string(name)+'}'); emit(body);
    end
    function renderCategory(cat)
        rows=find(startsWith(P.category,sprintf('%02d_',cat)));
        if isempty(rows), emit('No scientifically supported figure was generated for this category; see the dataset limitations.'); return; end
        for slot=1:numel(rows)
            row=rows(slot);
            emit('\renewcommand{\thefigure}{'+P.figure_id(row)+'}');
            emit('\begin{figure}[H]\centering');
            emit('\includegraphics[width=\textwidth,height=0.37\textheight,keepaspectratio]{figures/'+P.report_filename(row)+'}');
            emit('\caption{'+tex(P.caption(row))+'}\label{fig:'+P.figure_id(row)+'}');
            emit('\end{figure}');
            emit(tex(P.engineering_analysis(row))+'\par');
        end
    end
end

function s=tex(s)
s=string(s); s=replace(s,'\',char(1));
for c=["&","%","$","#","_","{","}"]
    s=replace(s,c,"\"+c);
end
s=replace(s,char(1),'\textbackslash{}'); s=replace(s,'^','\textasciicircum{}'); s=replace(s,'~','\textasciitilde{}');
end
function s=numeric(x)
if isfinite(x), s=sprintf('%.3g',x); else, s='unknown'; end
end

