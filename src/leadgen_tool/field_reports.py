from __future__ import annotations

from html import escape
from pathlib import Path
from itertools import groupby

from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import QWidget

from leadgen_tool.models import Lead


def export_leads_pdf(leads: list[Lead], destination: str | Path, title: str) -> Path:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(destination))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    _send_html_to_printer(printer, _render_leads_html(leads, title))
    return Path(destination)


def export_route_sheet_pdf(leads: list[Lead], destination: str | Path) -> Path:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(destination))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    _send_html_to_printer(printer, _render_route_sheet_html(leads))
    return Path(destination)


def export_scripts_pdf(scripts: list[dict[str, str]], destination: str | Path) -> Path:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(destination))
    _send_html_to_printer(printer, _render_scripts_html(scripts))
    return Path(destination)


def print_leads(parent: QWidget, leads: list[Lead], title: str) -> bool:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(title)
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    return _preview_html(parent, printer, _render_leads_html(leads, title), title)


def print_route_sheet(parent: QWidget, leads: list[Lead]) -> bool:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName("RouteForge Door-Knocking Sheet")
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    return _preview_html(
        parent,
        printer,
        _render_route_sheet_html(leads),
        "Preview Door-Knocking Sheet",
    )


def print_mapped_leads(parent: QWidget, leads: list[Lead]) -> bool:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName("RouteForge Route Order")
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    return _preview_html(
        parent,
        printer,
        _render_mapped_leads_html(leads),
        "Preview Route Order",
    )


def print_call_sheet(parent: QWidget, leads: list[Lead]) -> bool:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName("RouteForge Call List")
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    return _preview_html(parent, printer, _render_call_sheet_html(leads), "Preview Call List")


def print_scripts(parent: QWidget, scripts: list[dict[str, str]], title: str = "Preview Scripts") -> bool:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName("RouteForge Sales Script Cheat Sheet")
    return _preview_html(parent, printer, _render_scripts_html(scripts), title)


def _preview_html(parent: QWidget, printer: QPrinter, html: str, title: str) -> bool:
    dialog = QPrintPreviewDialog(printer, parent)
    dialog.setWindowTitle(title)
    dialog.paintRequested.connect(lambda preview_printer: _send_html_to_printer(preview_printer, html))
    dialog.exec()
    return True


def _send_html_to_printer(printer: QPrinter, html: str) -> None:
    document = QTextDocument()
    document.setHtml(html)
    page_rect = printer.pageRect(QPrinter.Unit.Point)
    if page_rect.isValid():
        document.setPageSize(page_rect.size())
    document.print_(printer)


def _render_route_sheet_html(leads: list[Lead]) -> str:
    rows = []
    stop_blocks = []
    for index, lead in enumerate(leads, start=1):
        notes = lead.notes or lead.quick_notes or ""
        reason = lead.lead_reason or "Good field prospect"
        stop_blocks.append(
            "<td class='stop-cell'>"
            f"<div><span class='stop'>STOP {index}</span> "
            f"<span class='business'>{escape(lead.business_name or 'Unnamed business')}</span></div>"
            f"<div class='address'>{escape(lead.full_address or 'Address not listed')}</div>"
            "<table class='mini'><tr>"
            f"<td><b>Phone:</b> {escape(lead.phone or '')}</td>"
            f"<td><b>Best:</b> {escape(lead.recommended_visit_window or 'Anytime')}</td>"
            f"<td><b>Priority:</b> {escape(lead.priority_tier or lead.action_priority or '')}</td>"
            f"<td><b>Status:</b> {escape(lead.status or 'New')}</td>"
            "</tr></table>"
            f"<div class='reason'>{escape(reason)}</div>"
            "<div class='checks'>[ ] Called &nbsp; [ ] Door &nbsp; [ ] Interested &nbsp; [ ] Follow Up</div>"
            f"<div class='notes'><b>Notes:</b> {escape(notes)}</div>"
            "</td>"
        )
    for index in range(0, len(stop_blocks), 2):
        left = stop_blocks[index]
        right = stop_blocks[index + 1] if index + 1 < len(stop_blocks) else "<td class='stop-cell empty'></td>"
        rows.append(f"<tr>{left}{right}</tr>")
    body = "".join(rows) or "<tr><td class='stop-cell'>No route stops selected.</td></tr>"
    return f"""
    <html>
      <head>
        <style>
          @page {{ margin: 0.25in; }}
          body {{ font-family: Arial, sans-serif; font-size: 7.2pt; color: #17212b; }}
          h1 {{ color: #17212b; font-size: 13pt; margin: 0; }}
          h2 {{ color: #2563eb; font-size: 10pt; margin: 0 0 3px 0; }}
          .subtitle {{ color: #536577; margin-bottom: 6px; font-size: 7pt; }}
          .sheet {{ width: 100%; border-collapse: separate; border-spacing: 5px; }}
          .sheet tr {{ page-break-inside: avoid; }}
          .stop-cell {{ width: 50%; border: 1px solid #cfd9e3; padding: 5px; vertical-align: top; }}
          .empty {{ border: 0; }}
          .stop {{ color: #2563eb; font-weight: 800; font-size: 7pt; }}
          .business {{ font-weight: 800; font-size: 8.2pt; }}
          .address {{ color: #25364a; margin-top: 2px; }}
          .mini {{ width: 100%; border-collapse: collapse; margin-top: 3px; }}
          .mini td {{ border: 0; padding: 0 5px 0 0; font-size: 6.8pt; white-space: nowrap; }}
          .reason {{ color: #536577; font-size: 6.8pt; margin-top: 2px; }}
          .checks {{ white-space: nowrap; font-size: 6.8pt; margin-top: 3px; }}
          .notes {{ border-top: 1px solid #d8e2ec; margin-top: 3px; padding-top: 2px; min-height: 10px; }}
        </style>
      </head>
      <body>
        <h1>RouteForge</h1>
        <h2>Door-Knocking Sheet</h2>
        <div class="subtitle">Plan your route. Knock more doors. Close more deals.</div>
        <table class="sheet">
          <tbody>{body}</tbody>
        </table>
      </body>
    </html>
    """


def _render_mapped_leads_html(leads: list[Lead]) -> str:
    mapped = list(leads)
    rows = []
    for index, lead in enumerate(mapped, start=1):
        rows.append(
            "<tr>"
            f"<td class='stop'>{index}</td>"
            f"<td class='business'>{escape(lead.business_name)}</td>"
            f"<td>{escape(lead.full_address)}</td>"
            f"<td>{escape(lead.phone or '')}</td>"
            f"<td>{escape(lead.priority_tier or '')}</td>"
            f"<td>{escape(lead.recommended_visit_window or '')}</td>"
            f"<td>{escape(lead.status or 'New')}</td>"
            "</tr>"
        )
    body = "".join(rows) or "<tr><td colspan='7'>No businesses in route order available.</td></tr>"
    return f"""
    <html>
      <head>
        <style>
          @page {{ margin: 0.25in; }}
          body {{ font-family: Arial, sans-serif; font-size: 7.8pt; color: #17212b; }}
          h1 {{ color: #17212b; font-size: 13pt; margin: 0; }}
          h2 {{ color: #2563eb; font-size: 10pt; margin: 0 0 3px 0; }}
          .subtitle {{ color: #536577; margin-bottom: 6px; font-size: 7pt; }}
          table {{ width: 100%; border-collapse: collapse; }}
          th, td {{ border: 1px solid #cfd9e3; padding: 3px 4px; vertical-align: top; }}
          th {{ background: #17212b; color: white; text-align: left; font-size: 7pt; }}
          tr {{ page-break-inside: avoid; }}
          tr:nth-child(even) td {{ background: #f4f8fc; }}
          .stop {{ width: 24px; color: #2563eb; font-weight: 800; text-align: center; }}
          .business {{ font-weight: 800; }}
        </style>
      </head>
      <body>
        <h1>RouteForge</h1>
        <h2>Route Order</h2>
        <div class="subtitle">Plan your route. Knock more doors. Close more deals.</div>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Business</th>
              <th>Address</th>
              <th>Phone</th>
              <th>Tier</th>
              <th>Visit Window</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </body>
    </html>
    """


def _render_call_sheet_html(leads: list[Lead]) -> str:
    phone_leads = [lead for lead in leads if lead.phone.strip()]
    rows = []
    for lead in phone_leads:
        rows.append(
            "<tr>"
            f"<td class='business'>{escape(lead.business_name or 'Unnamed business')}</td>"
            f"<td class='phone'>{escape(lead.phone)}</td>"
            f"<td>{escape(lead.full_address or '')}</td>"
            f"<td>{escape(lead.recommended_visit_window or 'Anytime today')}</td>"
            f"<td>{escape(lead.status or 'New')}</td>"
            "<td class='notes'>&nbsp;</td>"
            "</tr>"
        )
    body = "".join(rows) or "<tr><td colspan='6'>No leads with phone numbers selected.</td></tr>"
    return f"""
    <html>
      <head>
        <style>
          @page {{ margin: 0.25in; }}
          body {{ font-family: Arial, sans-serif; font-size: 7.8pt; color: #17212b; }}
          h1 {{ color: #17212b; font-size: 13pt; margin: 0; }}
          h2 {{ color: #2563eb; font-size: 10pt; margin: 0 0 3px 0; }}
          .subtitle {{ color: #536577; margin-bottom: 6px; font-size: 7pt; }}
          table {{ width: 100%; border-collapse: collapse; }}
          th, td {{ border: 1px solid #cfd9e3; padding: 3px 4px; vertical-align: top; }}
          th {{ background: #17212b; color: white; text-align: left; font-size: 7pt; }}
          tr {{ page-break-inside: avoid; }}
          tr:nth-child(even) td {{ background: #f4f8fc; }}
          .business {{ font-weight: 800; }}
          .phone {{ font-weight: 800; white-space: nowrap; }}
          .notes {{ width: 20%; }}
        </style>
      </head>
      <body>
        <h1>RouteForge</h1>
        <h2>Call List</h2>
        <div class="subtitle">Plan your route. Knock more doors. Close more deals.</div>
        <table>
          <thead>
            <tr>
              <th>Business</th>
              <th>Phone</th>
              <th>Address</th>
              <th>Best Time</th>
              <th>Status</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </body>
    </html>
    """


def _render_scripts_html(scripts: list[dict[str, str]]) -> str:
    sorted_scripts = sorted(scripts, key=lambda item: (item.get("category", ""), item.get("title", "")))
    groups = []
    for category, grouped in groupby(sorted_scripts, key=lambda item: item.get("category", "Scripts")):
        cards = []
        for script in grouped:
            cards.append(
                "<div class='script'>"
                f"<h3>{escape(script.get('title', 'Script'))}</h3>"
                f"<div class='use-case'>{escape(script.get('use_case', ''))}</div>"
                f"<div class='text'>{escape(script.get('text', '')).replace(chr(10), '<br>')}</div>"
                "</div>"
            )
        groups.append(
            f"<section><h2>{escape(category)}</h2>{''.join(cards)}</section>"
        )
    body = "".join(groups) or "<p>No scripts selected.</p>"
    return f"""
    <html>
      <head>
        <style>
          @page {{ margin: 0.35in; }}
          body {{ font-family: Arial, sans-serif; font-size: 8.5pt; color: #17212b; }}
          h1 {{ color: #17212b; font-size: 16pt; margin: 0; }}
          .subtitle {{ color: #536577; margin: 0 0 10px 0; }}
          h2 {{ color: #2563eb; font-size: 12pt; margin: 12px 0 6px 0; border-bottom: 1px solid #cfd9e3; }}
          h3 {{ font-size: 10pt; margin: 0 0 2px 0; }}
          .script {{ border: 1px solid #d8e2ec; padding: 6px; margin: 0 0 6px 0; page-break-inside: avoid; }}
          .use-case {{ color: #536577; font-style: italic; margin-bottom: 4px; }}
          .text {{ line-height: 1.3; }}
        </style>
      </head>
      <body>
        <h1>RouteForge</h1>
        <h2>Sales Script Cheat Sheet</h2>
        <div class="subtitle">Plan your route. Knock more doors. Close more deals.</div>
        {body}
      </body>
    </html>
    """


def _render_leads_html(leads: list[Lead], title: str) -> str:
    rows = []
    for index, lead in enumerate(leads, start=1):
        rows.append(
            "<tr>"
            f"<td class='stop'>{index}</td>"
            f"<td>{escape(lead.action_priority)}</td>"
            f"<td>{escape(lead.business_name)}</td>"
            f"<td>{escape(lead.full_address)}</td>"
            f"<td>{escape(lead.phone)}</td>"
            f"<td>{escape(lead.recommended_visit_window)}</td>"
            f"<td>{escape(lead.status or 'New')}</td>"
            f"<td>{escape(lead.quick_notes or lead.lead_reason)}</td>"
            "</tr>"
        )
    body = "".join(rows) or (
        "<tr><td colspan='8'>No leads selected.</td></tr>"
    )
    return f"""
    <html>
      <head>
        <style>
          @page {{ margin: 0.25in; }}
          body {{ font-family: Arial, sans-serif; font-size: 7.8pt; color: #17212b; }}
          h1 {{ color: #17212b; font-size: 13pt; margin: 0 0 3px 0; }}
          .subtitle {{ color: #536577; margin-bottom: 6px; font-size: 7pt; }}
          table {{ width: 100%; border-collapse: collapse; }}
          th, td {{ border: 1px solid #cfd9e3; padding: 3px 4px; vertical-align: top; }}
          th {{ background: #17212b; color: white; text-align: left; font-size: 7pt; }}
          tr {{ page-break-inside: avoid; }}
          tr:nth-child(even) td {{ background: #f4f8fc; }}
          .stop {{ color: #2563eb; font-weight: 700; text-align: center; }}
        </style>
      </head>
      <body>
        <h1>{escape(title)}</h1>
        <div class="subtitle">Plan your route. Knock more doors. Close more deals.</div>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Score</th>
              <th>Business</th>
              <th>Address</th>
              <th>Phone</th>
              <th>Visit Window</th>
              <th>Status</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </body>
    </html>
    """
