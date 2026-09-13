from __future__ import annotations
from io import BytesIO
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFont, ImageFilter

NAVY='#061526'; PANEL='#0b2942'; PANEL2='#0f3552'; CYAN='#35d8ff'; BLUE='#118ff7'
GREEN='#16c76f'; YELLOW='#ffc61a'; RED='#ff2731'; INK='#071526'; MUTED='#58758c'
WHITE='#f8fbff'; LINE='#c7ddea'; SOFT='#eef6fb'; VIOLET='#9367ef'; CEIBO='#d71935'


def _font_candidates(bold=False):
    return (['/System/Library/Fonts/Supplemental/Arial Bold.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
            if bold else ['/System/Library/Fonts/Supplemental/Arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])

def _font(size,bold=False):
    for p in _font_candidates(bold):
        if Path(p).exists():
            return ImageFont.truetype(p,size=size)
    return ImageFont.load_default()

def _fit(draw,text,max_w,max_size,min_size=10,bold=False):
    text=str(text)
    for s in range(max_size,min_size-1,-1):
        f=_font(s,bold)
        if draw.textbbox((0,0),text,font=f)[2] <= max_w:
            return f
    return _font(min_size,bold)

def _rounded(d,box,r,fill,outline=None,width=1):
    d.rounded_rectangle(box,radius=r,fill=fill,outline=outline,width=width)

def _circle(d,cx,cy,r,fill,outline=None,width=1):
    d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=fill,outline=outline,width=width)

def _shadow(img, box, radius=18, alpha=38, blur=18):
    layer=Image.new('RGBA',img.size,(0,0,0,0)); ld=ImageDraw.Draw(layer)
    ld.rounded_rectangle(box,radius=radius,fill=(0,22,42,alpha))
    layer=layer.filter(ImageFilter.GaussianBlur(blur)); img.alpha_composite(layer)

def _draw_paw(img, cx, cy, scale=1.0):
    # futuristic paw with cyan glow and dark-blue body
    glow=Image.new('RGBA',img.size,(0,0,0,0)); gd=ImageDraw.Draw(glow)
    s=scale
    body=(18,139,242,255)
    gd.ellipse((cx-42*s,cy-2*s,cx+42*s,cy+66*s),fill=body)
    toes=[(-52,-38,20,26),(-18,-56,18,28),(18,-56,18,28),(52,-38,20,26)]
    for dx,dy,rx,ry in toes:
        gd.ellipse((cx+(dx-rx)*s,cy+(dy-ry)*s,cx+(dx+rx)*s,cy+(dy+ry)*s),fill=body)
    soft=glow.filter(ImageFilter.GaussianBlur(int(18*s))); img.alpha_composite(soft); img.alpha_composite(glow)
    d=ImageDraw.Draw(img)
    d.ellipse((cx-22*s,cy+8*s,cx+6*s,cy+28*s),fill=(120,225,255,120))
    d.arc((cx-46*s,cy-4*s,cx+46*s,cy+68*s),200,330,fill='#9cecff',width=max(1,int(3*s)))


def _draw_ceibo(img, cx, cy, scale=1.0):
    d=ImageDraw.Draw(img); s=scale
    # stem + leaves
    d.line((cx+5*s,cy+44*s,cx+18*s,cy+104*s),fill='#3d7d44',width=max(2,int(5*s)))
    d.ellipse((cx+8*s,cy+72*s,cx+58*s,cy+96*s),fill='#4d9457',outline='#2e6537')
    # layered petals
    petals=[
        [(-8,18),(-55,-10),(-42,-55),(-4,-33)],
        [(0,10),(8,-66),(52,-48),(36,-6)],
        [(4,12),(64,-12),(74,30),(18,36)],
        [(-2,14),(-26,58),(-64,34),(-42,0)],
        [(6,8),(30,-22),(48,4),(22,26)],
    ]
    for poly in petals:
        pts=[(cx+x*s,cy+y*s) for x,y in poly]
        d.polygon(pts,fill=CEIBO,outline='#951426')
    d.ellipse((cx-9*s,cy-7*s,cx+15*s,cy+17*s),fill='#f6c244')
    d.line((cx+5*s,cy+3*s,cx+44*s,cy+42*s),fill='#f4e4aa',width=max(1,int(3*s)))
    for off in (0,10,20): _circle(d,cx+(42+off)*s,cy+(41+off*.25)*s,2.5*s,'#ffd95c')


def _donut(d,box,values,colors):
    total=max(sum(values),1); start=-90
    for v,c in zip(values,colors):
        sweep=360*v/total; d.pieslice(box,start=start,end=start+sweep,fill=c); start+=sweep
    x0,y0,x1,y1=box; inset=int((x1-x0)*.33)
    d.ellipse((x0+inset,y0+inset,x1-inset,y1-inset),fill=WHITE)


def _kpi_icon(d,kind,cx,cy,col):
    _circle(d,cx,cy,29,PANEL2,outline=col,width=2)
    if kind=='cases':
        d.rounded_rectangle((cx-15,cy-9,cx+15,cy+11),radius=4,outline=col,width=3); d.line((cx-8,cy-14,cx+6,cy-14),fill=col,width=3)
    elif kind=='ok':
        d.line((cx-13,cy,cx-3,cy+10,cx+15,cy-11),fill=col,width=5)
    elif kind=='wait':
        _circle(d,cx,cy,14,None,outline=col,width=3); d.line((cx,cy,cx,cy-9),fill=col,width=3); d.line((cx,cy,cx+8,cy+5),fill=col,width=3)
    elif kind=='warn':
        d.polygon([(cx,cy-16),(cx-17,cy+14),(cx+17,cy+14)],outline=col); d.line((cx,cy-7,cx,cy+5),fill=col,width=3); _circle(d,cx,cy+10,2,col)
    elif kind=='tasks':
        for yy in (-9,0,9): _circle(d,cx-11,cy+yy,2,col); d.line((cx-4,cy+yy,cx+13,cy+yy),fill=col,width=2)
    else:
        d.rectangle((cx-14,cy-12,cx+14,cy+14),outline=col,width=2); d.line((cx-8,cy-17,cx-8,cy-8),fill=col,width=3); d.line((cx+8,cy-17,cx+8,cy-8),fill=col,width=3)


def _sem_key(value:str)->str:
    s=str(value or '').upper()
    if 'ROJO' in s: return 'ROJO'
    if 'AMARILLO' in s: return 'AMARILLO'
    return 'VERDE'


def build_report_image(agent:str,jurisdiction:str,report_rows:list[dict[str,Any]],tasks:list[dict[str,Any]],assets:Path,version:str='V15')->bytes:
    W,H=1800,1050
    img=Image.new('RGBA',(W,H),WHITE); d=ImageDraw.Draw(img)

    counts={'VERDE':0,'AMARILLO':0,'ROJO':0}; standard=complex_=0
    for r in report_rows:
        counts[_sem_key(r.get('Semáforo'))]+=1
        if str(r.get('Clasificación','')).upper().startswith('COMP'): complex_+=1
        else: standard+=1
    total=max(sum(counts.values()),1)
    maj=max(counts,key=counts.get) if report_rows else 'VERDE'
    mcol={'VERDE':GREEN,'AMARILLO':YELLOW,'ROJO':RED}[maj]
    mword={'VERDE':'TODO BIEN','AMARILLO':'NO TE DUERMAS','ROJO':'ATENCIÓN'}[maj]
    task_open=[t for t in tasks if t.get('status') not in ('CUMPLIDA','CANCELADA')]
    task_over=sum(1 for t in task_open if t.get('status')=='VENCIDA')

    # HEADER PROFESIONAL: sin logo ni Sol. Título y datos alineados a la izquierda.
    d=ImageDraw.Draw(img)
    title_font=_font(54,True)
    name_font=_font(26,True)
    d.text((70,48),'REPORTE DE GESTIÓN',font=title_font,fill=INK)
    d.text((70,118),f'{agent.upper()}  |  {jurisdiction.upper()}',font=name_font,fill=BLUE)

    # executive status, centered and bold
    _circle(d,1660,76,42,mcol)
    _circle(d,1647,62,9,'#ffffff')
    d.text((1660,136),mword,font=_fit(d,mword,250,34,24,True),fill=mcol,anchor='ma')
    d.line((35,190,1765,190),fill=BLUE,width=3)

    # KPI strip with shadow and balanced spacing
    kpis=[('TRABAJOS ACTIVOS',len(report_rows),BLUE,'cases'),('EN TÉRMINO',counts['VERDE'],GREEN,'ok'),('EN ATENCIÓN',counts['AMARILLO'],YELLOW,'wait'),('CRÍTICOS',counts['ROJO'],RED,'warn'),('TAREAS ABIERTAS',len(task_open),CYAN,'tasks'),('TAREAS VENCIDAS',task_over,RED,'calendar')]
    x0=35; gap=14; cw=(1730-gap*5)//6; y=215; ch=132
    for i,(lab,val,colr,kind) in enumerate(kpis):
        x=x0+i*(cw+gap); _shadow(img,(x,y,x+cw,y+ch),16,28,12); d=ImageDraw.Draw(img)
        _rounded(d,(x,y,x+cw,y+ch),16,PANEL,outline=colr,width=2)
        _kpi_icon(d,kind,x+48,y+56,colr)
        d.text((x+113,y+48),str(val),font=_font(40,True),fill=colr,anchor='mm')
        d.text((x+cw/2,y+101),lab,font=_fit(d,lab,cw-18,16,11,True),fill=WHITE,anchor='mm')

    # CONTROL DASHBOARD: centered, compact, symmetric
    _shadow(img,(55,420,610,620),18,24,10); d=ImageDraw.Draw(img)
    _rounded(d,(55,420,610,620),18,'#fbfdff',outline=LINE,width=2)
    # no word "Clasificación"; just two compact cards
    for idx,(name,val,colr) in enumerate([('ESTÁNDAR',standard,BLUE),('COMPLEJO',complex_,VIOLET)]):
        bx=85+idx*260; _rounded(d,(bx,455,bx+230,585),14,SOFT,outline='#c9ddea',width=1)
        _circle(d,bx+35,495,12,colr); d.text((bx+62,487),name,font=_font(17,True),fill=INK)
        d.text((bx+115,548),str(val),font=_font(38,True),fill=INK,anchor='mm')

    _donut(d,(700,410,980,690),[counts['VERDE'],counts['AMARILLO'],counts['ROJO']],[GREEN,YELLOW,RED])

    _shadow(img,(1050,430,1505,610),18,22,10); d=ImageDraw.Draw(img)
    _rounded(d,(1050,430,1505,610),18,'#fbfdff',outline=LINE,width=2)
    for idx,(name,colr) in enumerate([('VERDE',GREEN),('AMARILLO',YELLOW),('ROJO',RED)]):
        bx=1070+idx*145
        if idx: d.line((bx-8,448,bx-8,592),fill='#d8e5ee',width=1)
        _circle(d,bx+30,475,14,colr)
        pct=counts[name]/total*100 if report_rows else 0
        d.text((bx+30,520),name,font=_font(15,True),fill=MUTED,anchor='ma')
        d.text((bx+30,565),f'{pct:.0f}%',font=_font(34,True),fill=INK,anchor='ma')


    # detail table
    ty=720; d.text((50,ty-35),'DETALLE DE TRABAJOS',font=_font(25,True),fill='#0b4b78')
    cols=[('SEM.',72),('TRABAJO',168),('CLASIFICACIÓN',175),('ASIGNACIÓN',145),('ÚLTIMO MOV.',180),('DÍAS S/ACT.',145),('% PLAZO',118),('RESTAN',110),('MOTIVO',557)]
    x=45
    for label,cw2 in cols:
        d.rectangle((x,ty,x+cw2,ty+40),fill=PANEL)
        d.text((x+cw2/2,ty+20),label,font=_fit(d,label,cw2-10,14,10,True),fill=WHITE,anchor='mm')
        x+=cw2
    yy=ty+40; rh=43
    for i,r in enumerate(report_rows[:5]):
        bg='#ffffff' if i%2==0 else '#edf5fa'; x=45; sem=_sem_key(r.get('Semáforo')); scol={'VERDE':GREEN,'AMARILLO':YELLOW,'ROJO':RED}[sem]
        vals=['',r.get('Trabajo','—'),r.get('Clasificación','—'),r.get('Asignación','—'),r.get('Último movimiento','—'),r.get('Días sin actividad','—'),r.get('% consumido','—'),r.get('Días restantes','—'),r.get('Motivo','—')]
        for ci,((_,cw2),val) in enumerate(zip(cols,vals)):
            d.rectangle((x,yy,x+cw2,yy+rh),fill=bg,outline=LINE,width=1)
            if ci==0: _circle(d,x+cw2/2,yy+rh/2,10,scol)
            else:
                text=str(val); f=_fit(d,text,cw2-14,14,10,False)
                while len(text)>4 and d.textbbox((0,0),text,font=f)[2] > cw2-14:
                    text=text[:-2]+'…'
                d.text((x+8,yy+rh/2),text,font=f,fill=INK,anchor='lm')
            x+=cw2
        yy+=rh

    # footer
    fy=1000; d.rectangle((0,fy,W,H),fill=NAVY)
    d.text((45,1025),'PATÁN  |  SISTEMA DE CONTROL Y SEGUIMIENTO',font=_font(14,True),fill=WHITE,anchor='lm')

    out=BytesIO(); img.convert('RGB').save(out,'PNG',optimize=True); return out.getvalue()


def png_to_pdf(png_bytes:bytes)->bytes:
    im=Image.open(BytesIO(png_bytes)).convert('RGB')
    out=BytesIO(); im.save(out,'PDF',resolution=150.0); return out.getvalue()
