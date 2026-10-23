from __future__ import annotations

import csv
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).resolve().parent / "SmartTE_Presentation_Source.pdf"
DATA = ROOT / "results/processed/m5_campaign_20261011T115819Z/metrics_summary.csv"
OUT = ROOT / "presentation"
PDF_OUT = OUT / "SmartTE_Presentation_Final.pdf"
PPTX_OUT = OUT / "SmartTE_Presentation_Final.pptx"
PNG_OUT = OUT / "results_slide.png"
W, H = 1440, 810


def read_data():
    raw = list(csv.DictReader(DATA.open(encoding="utf-8-sig", newline="")))
    selected = {}
    for row in raw:
        if row["experiment_id"] != "E2-congestion":
            continue
        metric = row["metric"]
        if metric not in {"tcp_throughput_mbps", "rtt_avg_ms", "ping_loss_pct"}:
            continue
        scenario = row["scenario"]
        load = "5 Mbps" if "5Mbps" in scenario else "9 Mbps"
        if "STATIC_initialA" in scenario:
            policy = "Static (A)"
        elif "STATIC_initialB" in scenario:
            policy = "Static (B)"
        elif "_B_initialA" in scenario:
            policy = "Policy B"
        else:
            policy = "Policy C"
        selected.setdefault((load, policy), {})[metric] = row
    return selected


def fmt(row, digits=2, clip_low=False):
    mean = float(row["mean"])
    lo, hi = float(row["ci95_low"]), float(row["ci95_high"])
    if clip_low:
        lo = max(0.0, lo)
    return f"{mean:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"


def _png_bytes(image):
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def font(size, bold=False):
    p = Path(r"C:\Windows\Fonts") / ("arialbd.ttf" if bold else "arial.ttf")
    return ImageFont.truetype(str(p), size)


def render_slide(data):
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    black, gray, pale = (18, 20, 22), (90, 96, 102), (243, 244, 245)
    d.text((42, 28), "SmartTE  |  BACSE203 Computer Networks, Fall 2026", font=font(20), fill=black)
    d.line((42, 71, 1398, 71), fill=(220, 222, 224), width=2)
    d.text((42, 92), "Congestion results: throughput, RTT and packet loss (E2)", font=font(35, True), fill=black)
    d.text((42, 145), "Mean [descriptive 95% CI]; five trials per condition. Ping loss is receiver-side ICMP loss.", font=font(18), fill=gray)

    x0, y0 = 42, 208
    widths = [153, 210, 340, 340, 340]
    headers = ["UDP load", "Policy / path", "TCP throughput (Mbps)", "Mean ping RTT (ms)", "Ping loss (%)"]
    row_h = 48
    x = x0
    for w, label in zip(widths, headers):
        d.rectangle((x, y0, x+w, y0+row_h), fill=black, outline=black, width=1)
        f = font(18, True)
        box = d.textbbox((0, 0), label, font=f)
        d.text((x+(w-(box[2]-box[0]))/2, y0+12), label, font=f, fill="white")
        x += w

    policies = ["Static (A)", "Static (B)", "Policy B", "Policy C"]
    y = y0 + row_h
    for load in ["5 Mbps", "9 Mbps"]:
        for j, policy in enumerate(policies):
            vals = data[(load, policy)]
            cells = [load if j == 0 else "", policy,
                     fmt(vals["tcp_throughput_mbps"]),
                     fmt(vals["rtt_avg_ms"], clip_low=False),
                     fmt(vals["ping_loss_pct"], clip_low=True)]
            x = x0
            fill = "white" if j % 2 == 0 else pale
            for k, (w, value) in enumerate(zip(widths, cells)):
                d.rectangle((x, y, x+w, y+row_h), fill=fill, outline=(205, 208, 211), width=1)
                f = font(18 if k > 1 else 19, k < 2 and bool(value))
                box = d.textbbox((0, 0), value, font=f)
                tx = x+14 if k < 2 else x+(w-(box[2]-box[0]))/2
                d.text((tx, y+12), value, font=f, fill=black)
                x += w
            y += row_h

    d.text((42, 672), "At 9 Mbps, Policy C preserved TCP throughput but had higher RTT; Policy B had lower RTT but higher ping loss.", font=font(19), fill=black)
    d.text((42, 707), "Intervals are descriptive t-based 95% CIs (n = 5); ping-loss lower bounds are clipped at the physical limit of 0%.", font=font(16), fill=gray)
    d.text((42, 757), "Source: processed campaign m5_campaign_20261011T115819Z, E2-congestion metrics_summary.csv.", font=font(15), fill=gray)
    d.text((1372, 771), "9", font=font(17), fill=black)
    im.save(PNG_OUT)
    return im


def wrap_text(draw, text, f, max_w):
    words, lines, line = text.split(), [], ""
    for word in words:
        test = f"{line} {word}".strip()
        if draw.textbbox((0, 0), test, font=f)[2] <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return "\n".join(lines)


def render_literature_slide():
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    black, gray, pale, border = (18,20,22), (90,96,102), (244,245,246), (210,213,216)
    d.text((42,28),"SmartTE  |  BACSE203 Computer Networks, Fall 2026",font=font(20),fill=black)
    d.line((42,71,1398,71),fill=(220,222,224),width=2)
    d.text((42,92),"Literature review and research gap",font=font(35,True),fill=black)
    d.text((42,145),"Prior work motivates the problem; SmartTE tests a narrower, implementation-specific question.",font=font(19),fill=gray)
    cards=[
        (42,"What prior work establishes",[
            ("Centralized traffic engineering", "B4 and SWAN coordinate paths with demand, rates and priorities at WAN scale [8, 9]."),
            ("Data-center multipath", "Hedera, MicroTE and CONGA use global scheduling, traffic patterns or distributed congestion signals [7, 11, 19]."),
            ("Stability and safe updates", "ECMP disruption, consistent updates and hybrid-routing instability are distinct concerns [2, 13, 14].")]),
        (735,"Research gap addressed here",[
            ("Not a novelty claim", "Centralized traffic engineering and route-stability mechanisms are established; this project does not claim otherwise."),
            ("Bounded experiment", "Under one two-path topology and periodic max-link-utilization score, compare lower-score switching (B) with a 15 pp margin plus 5 s dwell (C)."),
            ("What we measure", "Successful route changes alongside TCP throughput, ping RTT/loss and controller observations across E1–E4.")])]
    for x,title,items in cards:
        d.rounded_rectangle((x,195,x+660,674),radius=8,fill="white",outline=border,width=2)
        d.text((x+24,218),title,font=font(24,True),fill=black)
        yy=270
        for head,body in items:
            d.text((x+24,yy),head,font=font(19,True),fill=black)
            txt=wrap_text(d,body,font(17),608)
            d.multiline_text((x+24,yy+30),txt,font=font(17),fill=(55,60,64),spacing=5)
            yy += 117
    d.text((42,700),"Contribution: a controlled emulation of this feedback loop, not a direct benchmark against production systems.",font=font(18,True),fill=black)
    d.text((42,742),"Evidence boundary: 110 trials, n = 5 per cell; descriptive intervals. No universal superiority or statistical significance is claimed.",font=font(15),fill=gray)
    d.text((1370,771),"13",font=font(17),fill=black)
    return im


COMPARISON_ROWS = [
    ("OSPF / ECMP [1, 2, 15, 16]", "IGP link-weight optimization or per-flow hashing; protocol analysis and network-wide studies.", "Different control granularity; not this per-poll centralized congestion feedback."),
    ("Hedera / MicroTE / CONGA [7, 11, 19]", "Large-flow scheduling, traffic-matrix prediction or distributed congestion feedback; data-center studies.", "More global flow context or in-network coordination than SmartTE's one-flow, two-path setup."),
    ("B4 / SWAN [8, 9]", "WAN-scale path, rate and priority coordination; production, prototype and data-driven evaluation.", "Different scale and objectives; SmartTE does not allocate rates or claim comparable performance."),
    ("Reitblatt / Tseng [13, 14]", "Consistent network updates and routing-stability methods; formal mechanisms and simulation.", "Update correctness and stability are related but distinct; SmartTE measures a margin/dwell policy in emulation."),
    ("SmartTE (this study)", "OS-Ken/OpenFlow 1.3; 1 s port-counter polling; Static vs B vs C in Mininet E1–E4.", "Measures throughput, RTT, ping loss and successful route changes; bounded evidence (n=5 per cell)."),
]


def render_comparison_slide():
    im=Image.new("RGB",(W,H),"white"); d=ImageDraw.Draw(im)
    black,gray,border,pale=(18,20,22),(90,96,102),(205,208,211),(243,244,245)
    d.text((42,28),"SmartTE  |  BACSE203 Computer Networks, Fall 2026",font=font(20),fill=black)
    d.line((42,71,1398,71),fill=(220,222,224),width=2)
    d.text((42,92),"Comparison with representative research",font=font(35,True),fill=black)
    d.text((42,145),"Different scopes and evaluation methods: this is a conceptual comparison, not a numerical benchmark.",font=font(18),fill=gray)
    x0,y0=42,202; widths=[260,560,594]; rh=94
    headers=["Work", "Approach / evidence", "Relation to SmartTE"]
    x=x0
    for w,h in zip(widths,headers):
        d.rectangle((x,y0,x+w,y0+52),fill=black,outline=black)
        d.text((x+14,y0+14),h,font=font(18,True),fill="white")
        x+=w
    y=y0+52
    for idx,row in enumerate(COMPARISON_ROWS):
        x=x0; fill="white" if idx%2==0 else pale
        for col,(w,txt) in enumerate(zip(widths,row)):
            d.rectangle((x,y,x+w,y+rh),fill=fill,outline=border,width=1)
            f=font(16,col==0)
            d.multiline_text((x+13,y+13),wrap_text(d,txt,f,w-26),font=f,fill=black,spacing=4)
            x+=w
        y+=rh
    d.text((42,748),"Sources: report references [1], [2], [7]–[9], [11], [13]–[16], [19].",font=font(15),fill=gray)
    d.text((1370,771),"14",font=font(17),fill=black)
    return im


def add_textbox(slide, x, y, w, h, text, size, bold=False, color=(18,20,22), align=PP_ALIGN.LEFT):
    shape=slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))
    tf=shape.text_frame; tf.clear(); tf.word_wrap=True
    tf.margin_left=tf.margin_right=Inches(.07); tf.margin_top=Inches(.035); tf.margin_bottom=Inches(.03)
    p=tf.paragraphs[0]; p.alignment=align
    run=p.add_run(); run.text=text; run.font.name="Arial"; run.font.size=Pt(size); run.font.bold=bold; run.font.color.rgb=RGBColor(*color)
    return shape


def add_native_literature_slide(prs):
    slide=prs.slides.add_slide(prs.slide_layouts[6]); slide.background.fill.solid(); slide.background.fill.fore_color.rgb=RGBColor(255,255,255)
    add_textbox(slide,.39,.23,12.5,.28,"SmartTE  |  BACSE203 Computer Networks, Fall 2026",11)
    line=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,Inches(.39),Inches(.64),Inches(12.1),Inches(.012)); line.fill.solid(); line.fill.fore_color.rgb=RGBColor(220,222,224); line.line.fill.background()
    add_textbox(slide,.39,.80,12.2,.48,"Literature review and research gap",20,True)
    add_textbox(slide,.39,1.20,12.2,.34,"Prior work motivates the problem; SmartTE tests a narrower, implementation-specific question.",11,color=(90,96,102))
    columns=[(.39,"What prior work establishes",[
        ("Centralized traffic engineering","B4 and SWAN coordinate paths with demand, rates and priorities at WAN scale [8, 9]."),
        ("Data-center multipath","Hedera, MicroTE and CONGA use global scheduling, traffic patterns or distributed congestion signals [7, 11, 19]."),
        ("Stability and safe updates","ECMP disruption, consistent updates and hybrid-routing instability are distinct concerns [2, 13, 14].")]),
        (6.80,"Research gap addressed here",[
        ("Not a novelty claim","Centralized traffic engineering and route-stability mechanisms are established; this project does not claim otherwise."),
        ("Bounded experiment","Under one two-path topology and periodic max-link-utilization score, compare lower-score switching (B) with a 15 pp margin plus 5 s dwell (C)."),
        ("What we measure","Successful route changes alongside TCP throughput, ping RTT/loss and controller observations across E1–E4.")])]
    for x,title,items in columns:
        shp=slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,Inches(x),Inches(1.72),Inches(6.0),Inches(4.45)); shp.fill.solid(); shp.fill.fore_color.rgb=RGBColor(255,255,255); shp.line.color.rgb=RGBColor(210,213,216)
        add_textbox(slide,x+.20,1.91,5.6,.45,title,15,True)
        y=2.43
        for head,body in items:
            add_textbox(slide,x+.20,y,5.6,.30,head,12,True)
            add_textbox(slide,x+.20,y+.32,5.6,.68,body,10,color=(55,60,64))
            y+=1.14
    add_textbox(slide,.39,6.34,12.3,.29,"Contribution: a controlled emulation of this feedback loop, not a direct benchmark against production systems.",10,True)
    add_textbox(slide,.39,6.66,12.3,.34,"Evidence boundary: 110 trials, n = 5 per cell; descriptive intervals. No universal superiority or statistical significance is claimed.",9,color=(90,96,102))
    add_textbox(slide,12.25,7.02,.25,.22,"13",9,align=PP_ALIGN.RIGHT)


def add_native_comparison_slide(prs):
    slide=prs.slides.add_slide(prs.slide_layouts[6]); slide.background.fill.solid(); slide.background.fill.fore_color.rgb=RGBColor(255,255,255)
    add_textbox(slide,.39,.23,12.5,.28,"SmartTE  |  BACSE203 Computer Networks, Fall 2026",11)
    line=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,Inches(.39),Inches(.64),Inches(12.1),Inches(.012)); line.fill.solid(); line.fill.fore_color.rgb=RGBColor(220,222,224); line.line.fill.background()
    add_textbox(slide,.39,.80,12.2,.48,"Comparison with representative research",20,True)
    add_textbox(slide,.39,1.20,12.2,.30,"Different scopes and evaluation methods: this is a conceptual comparison, not a numerical benchmark.",10,color=(90,96,102))
    table=slide.shapes.add_table(6,3,Inches(.39),Inches(1.64),Inches(12.1),Inches(4.92)).table
    for col,w in enumerate([2.18,4.68,5.24]): table.columns[col].width=Inches(w)
    table.rows[0].height=Inches(.46)
    for r in range(1,6): table.rows[r].height=Inches(.89)
    headers=["Work","Approach / evidence","Relation to SmartTE"]
    for c,label in enumerate(headers):
        cell=table.cell(0,c); cell.text=label; cell.fill.solid(); cell.fill.fore_color.rgb=RGBColor(18,20,22); cell.vertical_anchor=MSO_ANCHOR.MIDDLE
        for p in cell.text_frame.paragraphs:
            p.alignment=PP_ALIGN.LEFT
            for run in p.runs: run.font.name="Arial"; run.font.size=Pt(11); run.font.bold=True; run.font.color.rgb=RGBColor(255,255,255)
    for r,row in enumerate(COMPARISON_ROWS,1):
        for c,value in enumerate(row):
            cell=table.cell(r,c); cell.text=value; cell.fill.solid(); cell.fill.fore_color.rgb=RGBColor(255,255,255) if r%2 else RGBColor(243,244,245); cell.vertical_anchor=MSO_ANCHOR.MIDDLE
            cell.margin_left=Inches(.10); cell.margin_right=Inches(.10); cell.margin_top=Inches(.06); cell.margin_bottom=Inches(.04)
            for p in cell.text_frame.paragraphs:
                p.space_after=Pt(0)
                for run in p.runs: run.font.name="Arial"; run.font.size=Pt(9); run.font.bold=(c==0); run.font.color.rgb=RGBColor(18,20,22)
    add_textbox(slide,.39,6.68,12.0,.25,"Sources: report references [1], [2], [7]–[9], [11], [13]–[16], [19].",8,color=(90,96,102))
    add_textbox(slide,12.25,7.02,.25,.22,"14",9,align=PP_ALIGN.RIGHT)


def add_image_slide(prs, image_bytes):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_picture(BytesIO(image_bytes), 0, 0, width=prs.slide_width, height=prs.slide_height)


def add_native_results_slide(prs, data):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(255, 255, 255)

    def textbox(x, y, w, h, text, size, bold=False, color=(18, 20, 22), align=PP_ALIGN.LEFT):
        shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = shape.text_frame
        tf.clear()
        tf.margin_left = tf.margin_right = Inches(.04)
        tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run(); run.text = text
        run.font.name = "Arial"; run.font.size = Pt(size); run.font.bold = bold
        run.font.color.rgb = RGBColor(*color)
        return shape

    textbox(.39,.23,12.5,.28,"SmartTE  |  BACSE203 Computer Networks, Fall 2026",11)
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(.39), Inches(.64), Inches(12.1), Inches(.012))
    line.fill.solid(); line.fill.fore_color.rgb = RGBColor(220,222,224); line.line.fill.background()
    textbox(.39,.80,12.2,.48,"Congestion results: throughput, RTT and packet loss (E2)",20,True)
    textbox(.39,1.20,12.2,.30,"Mean [descriptive 95% CI]; five trials per condition. Ping loss is receiver-side ICMP loss.",10,color=(90,96,102))

    headers = ["UDP load", "Policy / path", "TCP throughput (Mbps)", "Mean ping RTT (ms)", "Ping loss (%)"]
    widths = [1.42, 1.92, 3.02, 3.02, 2.72]
    x0, y0, rh = .39, 1.62, .42
    x = x0
    for w, title in zip(widths, headers):
        shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y0), Inches(w), Inches(rh))
        shp.fill.solid(); shp.fill.fore_color.rgb = RGBColor(18,20,22)
        shp.line.color.rgb = RGBColor(18,20,22)
        textbox(x+.02,y0+.06,w-.04,rh-.08,title,10,True,(255,255,255),PP_ALIGN.CENTER)
        x += w
    policies = ["Static (A)", "Static (B)", "Policy B", "Policy C"]
    y = y0 + rh
    for load in ["5 Mbps", "9 Mbps"]:
        for j, policy in enumerate(policies):
            v = data[(load,policy)]
            vals = [load if j == 0 else "", policy, fmt(v["tcp_throughput_mbps"]), fmt(v["rtt_avg_ms"]), fmt(v["ping_loss_pct"], clip_low=True)]
            x = x0
            for k,(w,value) in enumerate(zip(widths,vals)):
                shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(rh))
                rgb = (255,255,255) if j % 2 == 0 else (243,244,245)
                shp.fill.solid(); shp.fill.fore_color.rgb = RGBColor(*rgb)
                shp.line.color.rgb = RGBColor(205,208,211)
                textbox(x+.08 if k < 2 else x+.03,y+.07,w-(.16 if k < 2 else .06),rh-.10,value,10,k < 2 and bool(value),align=PP_ALIGN.LEFT if k<2 else PP_ALIGN.CENTER)
                x += w
            y += rh
    textbox(.39,5.62,12.3,.30,"At 9 Mbps, Policy C preserved TCP throughput but had higher RTT; Policy B had lower RTT but higher ping loss.",11)
    textbox(.39,5.94,12.3,.38,"Intervals are descriptive t-based 95% CIs (n = 5); ping-loss lower bounds are clipped at the physical limit of 0%.",9,color=(90,96,102))
    textbox(.39,6.32,12.3,.28,"Source: processed campaign m5_campaign_20261011T115819Z, E2-congestion metrics_summary.csv.",8,color=(90,96,102))
    textbox(12.25,6.57,.24,.22,"9",9,align=PP_ALIGN.RIGHT)


def main():
    OUT.mkdir(exist_ok=True)
    source = fitz.open(SOURCE)
    data = read_data()
    slide_image = render_slide(data)
    literature_image = render_literature_slide()
    comparison_image = render_comparison_slide()
    pdf = fitz.open()
    for i, page in enumerate(source):
        if i == 12:
            for new_image in (literature_image, comparison_image):
                p = pdf.new_page(width=page.rect.width, height=page.rect.height)
                p.insert_image(p.rect, stream=_png_bytes(new_image))
        if i == 8:
            p = pdf.new_page(width=page.rect.width, height=page.rect.height)
            p.insert_image(p.rect, stream=PNG_OUT.read_bytes())
        else:
            p = pdf.new_page(width=page.rect.width, height=page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(2,2), alpha=False)
            if i == 12:
                last = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                ImageDraw.Draw(last).rectangle((920, 438, 1305, 520), fill="white")
                draw = ImageDraw.Draw(last)
                draw.rectangle((1310, 748, 1370, 790), fill="white")
                draw.text((1334, 756), "15", font=font(17), fill=(135,135,135))
                p.insert_image(p.rect, stream=_png_bytes(last))
                continue
            p.insert_image(p.rect, pixmap=pix)
    pdf.set_metadata({"title":"SmartTE Presentation — Final", "author":"SmartTE project team"})
    pdf.save(PDF_OUT, deflate=True)

    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)
    for i in range(len(source)):
        if i == 12:
            add_native_literature_slide(prs)
            add_native_comparison_slide(prs)
        if i == 8:
            add_native_results_slide(prs, data)
        else:
            page = source[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(2,2), alpha=False)
            image_bytes = pix.tobytes("png")
            if i == 12:
                last = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                ImageDraw.Draw(last).rectangle((920, 438, 1305, 520), fill="white")
                draw = ImageDraw.Draw(last)
                draw.rectangle((1310, 748, 1370, 790), fill="white")
                draw.text((1334, 756), "15", font=font(17), fill=(135,135,135))
                image_bytes = _png_bytes(last)
            add_image_slide(prs, image_bytes)
    prs.core_properties.title = "SmartTE Presentation — Final"
    prs.core_properties.subject = "Targeted E2 results update; original source supplied as PDF"
    prs.save(PPTX_OUT)
    print(f"Saved {PDF_OUT}")
    print(f"Saved {PPTX_OUT}")
    print("PPTX slide 9 uses editable native text and table cells; other slides retain the PDF-rendered originals as images.")


if __name__ == "__main__":
    main()
