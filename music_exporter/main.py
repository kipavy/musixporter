from music_exporter.sources.deezer import DeezerGatewaySource
from music_exporter.formatters.monochrome import MonochromeJsonOutput

def main():
    print("=== Modular Music Exporter ===")
    
    # 1. Initialize Modules
    source = DeezerGatewaySource()
    formatter = MonochromeJsonOutput()
    
    try:
        # 2. Authenticate
        source.authenticate()
        
        # 3. Fetch
        data = source.fetch_data()
        
        # 4. Save
        formatter.save(data, "monochrome_export.json")
        
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()