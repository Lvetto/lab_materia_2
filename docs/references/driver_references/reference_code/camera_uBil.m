

global camobject sb_pressed im0 im1 avgs filmdata
avgs = 16;
sb_pressed = false;

if ~isa(camobject,'webcam')
    newcamera
end

if isempty(im0)
    im0 = get_image;
end

if ~ishandle(10)
    figure(10);
    image(uint8(im0));
    hold on
    roiButton = uicontrol;
    roiButton.Style = "pushbutton";
    roiButton.String='set ROI';
    roiButton.Callback = @(src,event)(define_circle(10));
    
    exposureControl = uicontrol;
    exposureControl.Style = "slider";
    exposureControl.String='exposure';
    exposureControl.Position = [20 400 50 20];
    exposureControl.Callback = @(src,event)(exposureControl_changed(src));
    
    drawnow
end


if isempty(filmdata) %nargin>1
    define_circle(10) ;
else
    figure(10)
    hold on
    filmdata.hc = plot(filmdata.xy(1),filmdata.xy(2),'+r');
    [xc,yc] = cylinder(filmdata.r,100);
    filmdata.hr = plot(xc(1,:)'+filmdata.xy(1),yc(2,:)'+filmdata.xy(2),'r');
    hold off
end

%%
if ~ishandle(12)
    figure(12)
    
    stopButton = uicontrol;
    stopButton.Style = "pushbutton";
    stopButton.String='Stop';
    stopButton.Callback = @(src,event)(button_pressed);

    saveButton = uicontrol;
    saveButton.Style = "pushbutton";
    saveButton.String='Save';
    saveButton.Position = [220 400 80 20];
    saveButton.Callback = @(src,event)(save_button_pressed);
    
    
    resetButton = uicontrol;
    resetButton.Style = "pushbutton";
    resetButton.String='get reference image';
    resetButton.Position = [20 400 200 20];
    resetButton.Callback = @(src,event)(im0_button_pressed);
    
    lb = uicontrol;
    lb.Style = "slider";
    lb.Position = [300 400 200 20];
    lb.Callback = @(src,event)(slider_moved(src)); 
    
    roiButton12 = uicontrol;
    roiButton12.Style = "pushbutton";
    roiButton12.String='set ROI';
    roiButton12.Position = [450 20 80 20];
    roiButton12.Callback = @(src,event)(define_circle(12));

    drawnow
end

%%

% acquire image and get white level
if isfield(filmdata,'ii')
    cc=numel(filmdata.ii)+1;
else
    cc=1;
end
sb_pressed=false;
while ~sb_pressed
    tic
    
    im1 = get_image;
    if ~isempty(im1)
        figure(14);
        image(uint8(im1));
        im1 = im1-im0;
        imm=im1.*filmdata.mm;
        filmdata.ii(cc)=sum(255-imm(:))/filmdata.n;
        imm=im1.*filmdata.mm_in;
        filmdata.ii_in(cc)=sum(255-imm(:))/filmdata.n_in;
        imm=im1.*filmdata.mm_mid;
        filmdata.ii_mid(cc)=sum(255-imm(:))/filmdata.n_mid;

        imm=im1.*filmdata.mm1;
        filmdata.ii1(cc)=sum(255-imm(:))/filmdata.n1;
        imm=im1.*filmdata.mm2;
        filmdata.ii2(cc)=sum(255-imm(:))/filmdata.n2;
        imm=im1.*filmdata.mm3;
        filmdata.ii3(cc)=sum(255-imm(:))/filmdata.n3;
        imm=im1.*filmdata.mm4;
        filmdata.ii4(cc)=sum(255-imm(:))/filmdata.n4;
        
        
        figure(11)
        plot(cc,filmdata.ii(cc),'.b')
        drawnow
        hold on
        
        figure(13)
        subplot(2,1,1)
        plot(cc,filmdata.ii_in(cc)./filmdata.ii(cc) ,'.r',cc,filmdata.ii_mid(cc)./filmdata.ii(cc) ,'.b')
        hold on
        set(gca,'yscale','log')
        legend({'inner (25% radius) / total','middle (50% radius) / total'})
        subplot(2,1,2)
        plot(cc,100*filmdata.ii1(cc)./filmdata.ii(cc) ,'.r', cc,100*filmdata.ii2(cc)./filmdata.ii(cc) ,'.b' ,cc,100*filmdata.ii3(cc)./filmdata.ii(cc) ,'.g', cc,100*filmdata.ii4(cc)./filmdata.ii(cc) ,'.m')
        hold on
        legend({'1^s^t quadrant (%)','2^n^d quadrant (%)','3^r^d quadrant (%)','4^t^h quadrant (%)'})
        drawnow
        
        pause(5-toc)
        cc=cc+1;
        filmdata.dd = sqrt(sum((im1).^2,3));

        figure(12)
        filmdata.dd(filmdata.dd==0)=NaN;
        imagesc((filmdata.dd)),colorbar,
        if isfield(filmdata,'c_limits')
            clim(filmdata.c_limits);
        end
    else
        filmdata.ii(cc)=NaN;
        filmdata.ii_in(cc)=NaN;
        filmdata.ii_mid(cc)=NaN;
        filmdata.ii1(cc)=NaN;
        filmdata.ii2(cc)=NaN;
        filmdata.ii3(cc)=NaN;
        filmdata.ii4(cc)=NaN;
    end
end


%%
function button_pressed
    global sb_pressed
    sb_pressed = true;
end



function im0_button_pressed
    global im0 filmdata
    im0 = get_image;
    figure(10)
    image(uint8(im0))
    hold on
    hc = plot(filmdata.xy(1),filmdata.xy(2),'+r');
    [xc,yc] = cylinder(filmdata.r,100);
    hr = plot(xc(1,:)'+filmdata.xy(1),yc(2,:)'+filmdata.xy(2),'r');
    hold off
    filmdata.hr = hr;
    filmdata.hc = hc;
    drawnow
end



function slider_moved(src)
    global filmdata
    c0 = max(filmdata.dd(:));
    filmdata.c_limits = c0*(0.01+src.Value*2)*[0 1];
    clim(filmdata.c_limits);
end

function newcamera
    global camobject
    camobject = webcam;
    set(camobject,'WhiteBalanceMode','manual')
    set(camobject,'WhiteBalance',3900)
    set(camobject,'ExposureMode','manual')
    set(camobject,'Exposure',-5)
end

function exposureControl_changed(src)
    global camobject
    src
    disp(['Exposure set to ' num2str(-1-fix(12*src.Value))])
    set(camobject,'Exposure',-1-fix(12*src.Value))
end


function imm = get_image

    global camobject avgs 
    
    % integrate on a few images so to reduce noise
    try
        imm = double(snapshot(camobject));
        for jj=1:avgs-1
            imm = (imm*jj+double(snapshot(camobject)))/(jj+1);
        end
    catch
        imm = [];
        warning([datestr(now) ' - Image acquisition failed!'])
        clear camobject
        newcamera
    end

end


function define_circle(figure_number)
    global im0 filmdata
    figure(figure_number);
    % define circle using mouse
    xy = ginput(1);
    hold on
    hc = plot(xy(1),xy(2),'+r');
    r = norm(xy-ginput(1));
    [xc,yc] = cylinder(r,100);
    hr = plot(xc(1,:)'+xy(1),yc(2,:)'+xy(2),'r');
    
    % refine circle by moving center or edge according to the closest to click;
    % right click to exit
    b = 0;
    while b<3
        title('refine circle by moving center or edge according to which is closer to click position; right click to exit!')
        [x0, y0, b] = ginput(1);
        if figure_number==10 && exist('d')
            delete(filmdata.hr)
            delete(filmdata.hc)
        end
        if b < 3
            if norm(xy-[x0 y0])<r/2
                xy = [x0 y0];
            else
                r = norm(xy-[x0 y0]);
            end
        
            delete(hc)
            hc = plot(xy(1),xy(2),'+r');
            [xc,yc] = cylinder(r,100);
            delete(hr)
            hr = plot(xc(1,:)'+xy(1),yc(2,:)'+xy(2),'r');
        end
    end
    filmdata.xy = xy;
    filmdata.r = r;
    %filmdata.ii = [];
    title('')
    if figure_number==12
        delete(hr)
        delete(hc)
        figure(10)
        delete(filmdata.hr)
        delete(filmdata.hc)
        hold on
        hc = plot(xy(1),xy(2),'+r');
        [xc,yc] = cylinder(r,100);
        hr = plot(xc(1,:)'+xy(1),yc(2,:)'+xy(2),'r');
        hold off
        filmdata.hr = hr;
        filmdata.hc = hc;
    else
        if isfield(filmdata,'hr')
            delete(filmdata.hr)
            delete(filmdata.hc)
        end
        filmdata.hr = hr;
        filmdata.hc = hc;
    end
    hold off

    % prepare mask
    [cc,rr] = meshgrid((1:size(im0,2)),(1:size(im0,1)));
    filmdata.mm = sqrt((filmdata.xy(2)-rr).^2+(filmdata.xy(1)-cc).^2);
    filmdata.mm(filmdata.mm>r) = 0;
    filmdata.mm(filmdata.mm>0) = 1;
    filmdata.mm = repmat(filmdata.mm,[1 1 3]);

    filmdata.mm_mid = sqrt((filmdata.xy(2)-rr).^2+(filmdata.xy(1)-cc).^2);
    filmdata.mm_mid(filmdata.mm_mid>r/2) = 0;
    filmdata.mm_mid(filmdata.mm_mid>0) = 1;
    filmdata.mm_mid = repmat(filmdata.mm_mid,[1 1 3]);

    filmdata.mm_in = sqrt((filmdata.xy(2)-rr).^2+(filmdata.xy(1)-cc).^2);
    filmdata.mm_in(filmdata.mm_in>r/4) = 0;
    filmdata.mm_in(filmdata.mm_in>0) = 1;
    filmdata.mm_in = repmat(filmdata.mm_in,[1 1 3]);

    filmdata.mm1 = filmdata.mm & (filmdata.xy(2)-rr>0) & (filmdata.xy(1)-cc>0);
    filmdata.mm2 = filmdata.mm & (filmdata.xy(2)-rr>0) & (filmdata.xy(1)-cc<0);
    filmdata.mm4 = filmdata.mm & (filmdata.xy(2)-rr<0) & (filmdata.xy(1)-cc>0);
    filmdata.mm3 = filmdata.mm & (filmdata.xy(2)-rr<0) & (filmdata.xy(1)-cc<0);

    filmdata.n = sum(filmdata.mm(:));
    filmdata.n_mid = sum(filmdata.mm_mid(:));
    filmdata.n_in = sum(filmdata.mm_in(:));
    filmdata.n1 = sum(filmdata.mm1(:));
    filmdata.n2 = sum(filmdata.mm2(:));
    filmdata.n3 = sum(filmdata.mm3(:));
    filmdata.n4 = sum(filmdata.mm4(:));
end

function save_button_pressed
    global filmdata avgs im0 im1
    nome = ['c:\Mulan\Growth\uBil_Data\camera_ubil_' strrep(strrep(datestr(now),' ','_'),':','-')];
    savefig([10:14],nome)
    save(nome, 'filmdata', 'avgs', 'im0', 'im1')
end