from __future__ import annotations


from io import BytesIO
from datetime import date
from typing import Any
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.pdfgen.canvas import Canvas
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.piecharts import Pie

NAVY = colors.HexColor('#07111f')
PANEL = colors.HexColor('#102942')
CYAN = colors.HexColor('#50d4ff')
BLUE = colors.HexColor('#1d91ff')
GREEN = colors.HexColor('#36d17c')
YELLOW = colors.HexColor('#ffd84d')
RED = colors.HexColor('#ff5353')
WHITE = colors.HexColor('#f4f8ff')
MUTED = colors.HexColor('#a9c8df')


def _footer(canvas: Canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, landscape(A4)[0], 11*mm, stroke=0, fill=1)
    canvas.setFillColor(MUTED)
    canvas.setFont('Helvetica', 7.5)
    canvas.drawString(14*mm, 4.2*mm, 'Reporte de Gestión')
    canvas.drawRightString(landscape(A4)[0]-14*mm, 4.2*mm, f'Página {doc.page}')
    canvas.restoreState()


def build_management_report(agent: str, jurisdiction: str, report_rows: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm,
        topMargin=13*mm, bottomMargin=15*mm, title='PATÁN - Reporte de Gestión'
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle('patan_title', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=18,
                           leading=21, textColor=NAVY, alignment=TA_LEFT, spaceAfter=4)
    sub = ParagraphStyle('patan_sub', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9,
                         textColor=BLUE, leading=12, spaceAfter=8)
    small = ParagraphStyle('small', parent=styles['Normal'], fontSize=7.5, leading=9, textColor=NAVY)
    smallw = ParagraphStyle('smallw', parent=small, textColor=WHITE)

    story = []

    counts = {'VERDE':0,'AMARILLO':0,'ROJO':0}
    standard = complex_ = 0
    for r in report_rows:
        sem = str(r.get('Semáforo','')).upper()
        for k in counts:
            if k in sem: counts[k] += 1
        if str(r.get('Clasificación','')).upper().startswith('COMP'): complex_ += 1
        else: standard += 1
    task_open = [t for t in tasks if t.get('status') not in ('CUMPLIDA','CANCELADA')]
    task_over = sum(1 for t in task_open if t.get('status') == 'VENCIDA')
    task_ext = sum(1 for t in task_open if t.get('extension_days'))
    majority=max(counts, key=counts.get) if sum(counts.values()) else 'VERDE'
    majority_color={'VERDE':'#21b968','AMARILLO':'#f3c316','ROJO':'#e42121'}[majority]
    majority_word={'VERDE':'TODO BIEN','AMARILLO':'NO TE DUERMAS','ROJO':'ATENCIÓN'}[majority]
    paw_path=Path(__file__).resolve().parent/'assets'/'logo_pata.png'
    brand=Image(str(paw_path), width=23*mm, height=23*mm) if paw_path.exists() else Paragraph('🐾', title)
    head_left=Table([[brand, Paragraph('REPORTE DE GESTIÓN', title)], ['', Paragraph(f'{agent.upper()} &nbsp; | &nbsp; {jurisdiction.upper()} &nbsp; | &nbsp; {date.today().strftime("%d/%m/%Y")}', sub)]], colWidths=[28*mm,142*mm])
    head_left.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('SPAN',(0,0),(0,1)),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),3),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]))
    alert=Table([[Paragraph(f"<font color='{majority_color}' size='26'>●</font>", ParagraphStyle('dot', parent=sub, alignment=TA_CENTER, leading=28))],[Paragraph(f"<font color='{majority_color}'><b>{majority_word}</b></font>", ParagraphStyle('alert', parent=sub, fontSize=14, leading=16, alignment=TA_CENTER))]], colWidths=[48*mm], rowHeights=[11*mm,8*mm])
    alert.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    header_tbl=Table([[head_left,alert]], colWidths=[198*mm,52*mm])
    header_tbl.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(0,0),(-1,-1),1.2,BLUE),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    story += [header_tbl, Spacer(1, 3*mm)]

    kpis = [
        ('TRABAJOS ACTIVOS', len(report_rows), BLUE), ('EN TÉRMINO', counts['VERDE'], GREEN),
        ('ATENCIÓN', counts['AMARILLO'], YELLOW), ('CRÍTICOS', counts['ROJO'], RED),
        ('TAREAS ABIERTAS', len(task_open), CYAN), ('TAREAS VENCIDAS', task_over, RED),
    ]
    row=[]
    for label,val,col in kpis:
        cell = Table([[Paragraph(f'<b>{val}</b>', ParagraphStyle('k', parent=small, fontSize=16, alignment=TA_CENTER, textColor=col))],
                      [Paragraph(label, ParagraphStyle('kl', parent=small, fontSize=7, alignment=TA_CENTER, textColor=MUTED))]], colWidths=[38*mm], rowHeights=[19*mm,7*mm])
        cell.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PANEL),('BOX',(0,0),(-1,-1),0.6,col),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2)]))
        row.append(cell)
    kt=Table([row], colWidths=[43*mm]*6)
    kt.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    story += [kt, Spacer(1, 5*mm)]

    summary = Table([
        [Paragraph('<b>Clasificación</b>', smallw), Paragraph('<b>Trabajos</b>', smallw), Paragraph('<b>Tareas</b>', smallw), Paragraph('<b>Con prórroga</b>', smallw)],
        [Paragraph('ESTÁNDAR', small), standard, len(task_open), task_ext],
        [Paragraph('COMPLEJO', small), complex_, '', ''],
    ], colWidths=[45*mm,28*mm,28*mm,32*mm])
    summary.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),PANEL),('TEXTCOLOR',(0,0),(-1,0),WHITE),('GRID',(0,0),(-1,-1),0.35,colors.HexColor('#b9d9ee')),
        ('ALIGN',(1,1),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f0f6fb')])
    ]))
    story += [Paragraph('TABLERO DE CONTROL', sub), summary, Spacer(1, 3*mm)]
    if sum(counts.values()) > 0:
        drawing=Drawing(125*mm,34*mm)
        pie=Pie(); pie.x=12*mm; pie.y=1*mm; pie.width=30*mm; pie.height=30*mm
        pie.data=[counts['VERDE'],counts['AMARILLO'],counts['ROJO']]
        total_cases=max(sum(pie.data),1)
        pie.labels=[
            f"Verde {counts['VERDE']/total_cases*100:.0f}%",
            f"Amarillo {counts['AMARILLO']/total_cases*100:.0f}%",
            f"Rojo {counts['ROJO']/total_cases*100:.0f}%",
        ]; pie.slices[0].fillColor=GREEN; pie.slices[1].fillColor=YELLOW; pie.slices[2].fillColor=RED
        pie.sideLabels=True; pie.simpleLabels=False; pie.slices.strokeWidth=0.4; pie.slices.strokeColor=colors.white
        drawing.add(pie); story += [drawing, Spacer(1,2*mm)]

    story.append(Paragraph('DETALLE DE TRABAJOS', sub))
    headers=['Semáforo','Trabajo','Clasificación','Asignación','Último movimiento','Días s/actividad','% plazo','Restan','Motivo']
    data=[[Paragraph(f'<b>{h}</b>', smallw) for h in headers]]
    for r in report_rows:
        data.append([
            Paragraph(str(r.get('Semáforo','—')).replace('🟢 ','').replace('🟡 ','').replace('🔴 ',''), small), Paragraph(str(r.get('Trabajo','—')), small),
            Paragraph(str(r.get('Clasificación','—')), small), Paragraph(str(r.get('Asignación','—')), small),
            Paragraph(str(r.get('Último movimiento','—')), small), str(r.get('Días sin actividad','—')),
            str(r.get('% consumido','—')), str(r.get('Días restantes','—')), Paragraph(str(r.get('Motivo','—')), small)
        ])
    t=Table(data, repeatRows=1, colWidths=[24*mm,30*mm,25*mm,25*mm,30*mm,24*mm,19*mm,20*mm,66*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),PANEL),('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#a9c8df')),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('FONTSIZE',(0,1),(-1,-1),7),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f4f8fb')]),
        ('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)
    ]))
    story.append(t)
    if tasks:
        story += [PageBreak(), Paragraph('TAREAS Y VENCIMIENTOS', sub)]
        th=['Estado','Trabajo','Actuación','Destinatario','Notificación','Vencimiento','Respuesta','Prórroga']
        td=[[Paragraph(f'<b>{h}</b>', smallw) for h in th]]
        for x in tasks:
            td.append([
                Paragraph(str(x.get('status','—')),small), Paragraph(str(x.get('case_number','—')),small),
                Paragraph(str(x.get('title','—')),small), Paragraph(str(x.get('recipient') or '—'),small),
                Paragraph(str(x.get('notification_date') or '—'),small), Paragraph(str(x.get('due_date') or '—'),small),
                Paragraph(str(x.get('response_date') or '—'),small), Paragraph((f"{x.get('extension_days')} días" if x.get('extension_days') else '—'),small),
            ])
        tt=Table(td, repeatRows=1, colWidths=[24*mm,30*mm,52*mm,45*mm,29*mm,29*mm,29*mm,25*mm])
        tt.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),PANEL),('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#a9c8df')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f4f8fb')]),
            ('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)
        ]))
        story.append(tt)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
