from music_exporter.sources.deezer import DeezerGatewaySource
from music_exporter.converters.tidal_mapper import TidalMapper
from music_exporter.formatters.monochrome import MonochromeJsonOutput

def main():
    print("=== Deezer to Tidal (Monochrome) Exporter ===")
    
    # 1. Initialize Components
    source = DeezerGatewaySource()
    converter = TidalMapper()
    formatter = MonochromeJsonOutput()
    
    try:
        # 2. Get Data from Deezer
        source.authenticate()
        deezer_data = source.fetch_data()
        
        # 3. Convert IDs (Search on Tidal)
        print("\n--- Phase 2: Converting IDs to Tidal ---")
        tidal_data = converter.convert(deezer_data)
        
        # 4. Save to Monochrome Format
        formatter.save(tidal_data, "monochrome_tidal_import.json")
        
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()