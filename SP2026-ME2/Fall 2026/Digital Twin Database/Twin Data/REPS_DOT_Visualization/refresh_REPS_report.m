function refresh_REPS_report()
%REFRESH_REPS_REPORT Reassemble LaTeX after prose/layout edits, without replots.
% Requires a previously completed generate_REPS_plots execution.
out=fileparts(mfilename('fullpath'));
M=readtable(fullfile(out,'run_metrics.csv'),'TextType','string');
P=readtable(fullfile(out,'plot_manifest.csv'),'TextType','string');
V=jsondecode(fileread(fullfile(out,'validation','validation.json')));
T=table();
if isfile(fullfile(out,'thermal_fits.csv')), T=readtable(fullfile(out,'thermal_fits.csv'),'TextType','string'); end
write_REPS_report(out,M,P,string(V.metadata_notes),T);
extra=["analysis_evidence.csv";"figure_discussions.csv";"T0236_fft_spectrum.csv"];
extra=extra(isfile(fullfile(out,'report',extra)));
files=["main.tex";"plot_manifest.csv";"dataset_index.csv";"frequency_audit.csv";extra;"figures/"+P.report_filename];
zip(fullfile(out,'REPS_DOT_Overleaf.zip'),cellstr(files),fullfile(out,'report'));
fprintf('Report and Overleaf archive refreshed from the validated figure manifest.\n');
end
