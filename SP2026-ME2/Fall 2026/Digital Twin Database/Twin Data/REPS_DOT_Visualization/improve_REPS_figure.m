function improve_REPS_figure(f,id)
%IMPROVE_REPS_FIGURE Targeted presentation edits; plotted X/Y arrays unchanged.
ax=findall(f,'Type','axes'); legends=findall(f,'Type','legend');
set(f,'Position',[40 40 1150 520]);
if ismember(id,[5 23 24]), set(f,'Position',[40 40 1200 650]); end
for a=ax'
    a.FontSize=13; a.Title.FontSize=14; a.XLabel.FontSize=13; a.YLabel.FontSize=13;
    a.Title.String=replace(string(a.Title.String),["THERMAL_01_PART1","THERMAL_01_PART2"],["Segment 1","Segment 2"]);
    if ismember(id,[23 24])
        a.XLabel.String='Left temperature [deg C]';
        a.YLabel.String=replace(string(a.YLabel.String),', 1 s median','');
        texts=findall(a,'Type','text'); for t=texts', if contains(string(t.String),'slope'), t.FontSize=11; end, end
    end
end
for l=legends'
    l.FontSize=11; l.Box='off';
    if ismember(id,[6 9 18 19 21]), l.Location='southoutside'; end
    if ismember(id,[6 21]), l.NumColumns=3; end
    if id==6, l.NumColumns=2; end
    if id==5
        l.Location='northoutside'; l.NumColumns=3;
        l.String=replace(string(l.String),[" | ","PWM 0"],[", ",""]);
    end
end
if id==8
    a=ax(1); labels=string(a.XTickLabel);
    for k=1:numel(labels)
        tok=regexp(labels(k),'(Sep \d+).* / ([\d.]+) kg / (Left|Center|Right)','tokens','once');
        if ~isempty(tok), labels(k)=string(tok{1})+" / "+tok{2}+" kg / "+tok{3}; end
    end
    a.XTickLabel=labels; a.XTickLabelRotation=20; a.FontSize=11;
end
if ismember(id,[18 19])
    lim=vertcat(ax.YLim); limits=[min(lim(:,1)),max(lim(:,2))];
    for a=ax', a.YLim=limits; end % Common scale improves positional comparison.
end
if id==30
    for cb=findall(f,'Type','colorbar')', cb.FontSize=11; cb.Label.String='Mean dynamic z RMS [g]'; end
end
end
