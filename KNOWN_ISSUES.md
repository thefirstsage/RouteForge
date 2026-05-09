# Known Issues And Limitations

- Data quality depends on OpenStreetMap/Overpass coverage. Some markets have incomplete phone, website, email, hours, or address data.
- Email extraction is best-effort only and usually blank unless available from source tags or website/contact metadata.
- Phone and website enrichment is limited by public map data and does not currently use a paid business-data API.
- Pre-opening and construction opportunity detection is heuristic. It should be treated as a useful signal, not a guarantee.
- Property manager detection is based on keyword/category/name patterns and available source metadata.
- Route planning is intentionally simple. It groups and orders leads for field use but is not a full turn-by-turn navigation system.
- The map uses external Leaflet/CARTO resources, so map display requires internet access.
- Overpass endpoints may rate-limit or fail temporarily. The app includes fallback endpoints, but live scraping can still be slow or inconsistent.
- The packaged Windows build is large because PyInstaller includes the PySide6 and Qt WebEngine runtime.
- The app has no licensing, authentication, CRM sync, email outreach, or Google Sheets integration yet.
- The app is Windows-oriented right now. The Python source may run elsewhere, but packaging has only been prepared for Windows.
- The current UI is functional and polished for review, but additional usability testing with real non-technical users is recommended before selling widely.
