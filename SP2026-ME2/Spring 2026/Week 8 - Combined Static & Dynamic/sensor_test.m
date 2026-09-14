% =========================================================================
% Beautiful Plots from Excel File (no column headers)
%
% Assumes the Excel file has 6 columns in this order:
% Column 1 = LC1
% Column 2 = LC2
% Column 3 = Vibe Magnitude
% Column 4 = X
% Column 5 = Y
% Column 6 = Z
% =========================================================================

clc; clear; close all;

%% Read Excel data
data = readmatrix('data.csv');

LC1  = data(:,1);
LC2  = data(:,2);
Vibe = data(:,3);
Xacc = data(:,4);
Yacc = data(:,5);
Zacc = data(:,6);

% Sample index
n = size(data,1);
k = 1:n;

%% Create centered figure window using normalized coordinates
figure('Units','normalized', ...
       'Position',[0.08, 0.22, 0.84, 0.50], ...
       'Color','w', ...
       'Name','Load Cell and Accelerometer Data');

tiledlayout(1,3,'TileSpacing','compact','Padding','compact');

%% Subplot 1: Vibration motor magnitude
nexttile;
plot(k, Vibe, 'LineWidth', 1.8);
grid on;
box on;
xlabel('Sample Index', 'FontWeight','bold');
ylabel('Vibration Magnitude', 'FontWeight','bold');
title('Vibration Motor Magnitude', 'FontWeight','bold');
set(gca, 'FontSize', 11, 'LineWidth', 1.2);

%% Subplot 2: Load Cell 1 and Load Cell 2
nexttile;
plot(k, LC1, 'LineWidth', 1.8); hold on;
plot(k, LC2, 'LineWidth', 1.8);
grid on;
box on;
xlabel('Sample Index', 'FontWeight','bold');
ylabel('Load Cell Reading', 'FontWeight','bold');
title('Load Cell Responses', 'FontWeight','bold');
legend('Load Cell 1','Load Cell 2','Location','best');
set(gca, 'FontSize', 11, 'LineWidth', 1.2);

%% Subplot 3: X, Y, Z accelerometer components
nexttile;
plot(k, Xacc, 'LineWidth', 1.8); hold on;
plot(k, Yacc, 'LineWidth', 1.8);
plot(k, Zacc, 'LineWidth', 1.8);
grid on;
box on;
xlabel('Sample Index', 'FontWeight','bold');
ylabel('Acceleration (g)', 'FontWeight','bold');
title('Accelerometer Components', 'FontWeight','bold');
legend('X','Y','Z','Location','best');
set(gca, 'FontSize', 11, 'LineWidth', 1.2);

sgtitle('Experimental Sensor Data Overview', 'FontWeight','bold', 'FontSize', 14);