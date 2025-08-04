import xml.etree.ElementTree as ET
from tkinter import messagebox # Per mostrare errori se il file XML non è valido
import sys # Per sys.exit()

def load_app_config(xml_file_path="ftp_itscommconfig.xml"):
    """
    Carica la configurazione dell'applicazione dal file XML specificato.
    Restituisce un dizionario con i parametri di configurazione.
    Esce dall'applicazione se il file di configurazione non può essere caricato.
    """
    try:
        tree = ET.parse(xml_file_path)
        root = tree.getroot()

        config = {}

        # Configurazione FTP
        ftp_node = root.find("ftp")
        if ftp_node is not None:
            config["FTP_HOST"] = ftp_node.find("host").text.strip() if ftp_node.find("host") is not None else None
            config["FTP_USER"] = ftp_node.find("user").text.strip() if ftp_node.find("user") is not None else None
            config["FTP_PASS"] = ftp_node.find("password").text.strip() if ftp_node.find("password") is not None else None
            config["FTP_BASE_DIR"] = ftp_node.find("base_dir").text.strip() if ftp_node.find("base_dir") is not None else "/"
            config["FTP_DOC_DIR"] = ftp_node.find("doc_dir").text.strip() if ftp_node.find("doc_dir") is not None else None # Legge /DOC
            config["FTP_TARGET_DIR"] = "/importati" # Per file da base_dir
            config["FTP_DOC_TARGET_DIR"] = "/DOC_importati" # Per file da doc_dir
        else:
            messagebox.showerror("Errore Configurazione", "Sezione <ftp> mancante nel file XML.")
            sys.exit(1)

        # Configurazione Local
        local_node = root.find("local")
        if local_node is not None:
            config["LOCAL_IMPORT_DIR"] = local_node.find("import_dir").text.strip() if local_node.find("import_dir") is not None else None
            config["ORDINE_DIR"] = local_node.find("ordine_dir").text.strip() if local_node.find("ordine_dir") is not None else None
        else:
            messagebox.showerror("Errore Configurazione", "Sezione <local> mancante nel file XML.")
            sys.exit(1)

        if not config.get("LOCAL_IMPORT_DIR"):
             messagebox.showerror("Errore Configurazione", "Tag <import_dir> mancante o vuoto nella sezione <local>.")
             sys.exit(1)

        # Avviso se ORDINE_DIR non è configurato (ma non esce)
        if not config.get("ORDINE_DIR"):
            print("Avviso: Tag <ordine_dir> non configurato o vuoto. La copia secondaria non verrà eseguita.")


        # Configurazione Database (opzionale per ora, ma leggiamola se c'è)
        db_node = root.find("database")
        if db_node is not None:
            config["DB_DRIVER"] = db_node.find("driver").text.strip() if db_node.find("driver") is not None else None
            config["DB_SERVER"] = db_node.find("server").text.strip() if db_node.find("server") is not None else None
            config["DB_NAME"] = db_node.find("name").text.strip() if db_node.find("name") is not None else None
            config["DB_USER"] = db_node.find("user").text.strip() if db_node.find("user") is not None else None # Modificato per leggere <user>
            config["DB_PASS"] = db_node.find("password").text.strip() if db_node.find("password") is not None else None
            # I seguenti non sono più letti da <database> ma da <file_layouts> per ogni layout
            # config["DB_TARGET_TABLE"] = db_node.find("target_table").text.strip() if db_node.find("target_table") is not None else None
            # config["DB_FILE_FORMAT"] = db_node.find("file_format").text.strip() if db_node.find("file_format") is not None else None
            # config["DB_FILE_DELIMITER"] = db_node.find("file_delimiter").text.strip() if db_node.find("file_delimiter") is not None else None
            # config["DB_SKIP_HEADER_ROWS"] = int(db_node.find("skip_header_rows").text.strip()) if db_node.find("skip_header_rows") is not None and db_node.find("skip_header_rows").text.strip().isdigit() else 0
            config["DB_DEFAULT_SCHEMA"] = db_node.find("default_schema").text.strip() if db_node.find("default_schema") is not None else "dbo"

        # Caricamento File Layouts
        config["FILE_LAYOUTS"] = {}
        layouts_node = root.find("file_layouts")
        if layouts_node is not None:
            for layout_node in layouts_node.findall("layout"):
                record_type = layout_node.get("record_type")
                target_table = layout_node.get("target_table")
                schema = layout_node.get("schema", config.get("DB_DEFAULT_SCHEMA", "dbo")) # Usa default se non specificato
                if record_type and target_table:
                    columns = []
                    for col_node in layout_node.findall("column"):
                        col_details = {
                            "name": col_node.get("name"),
                            "start": int(col_node.get("start")),
                            "length": int(col_node.get("length")),
                            "type": col_node.get("type", "str"), # Default a stringa
                            "scale": int(col_node.get("scale")) if col_node.get("scale") is not None else None,
                            "format": col_node.get("format"),
                            "is_pk": col_node.get("pk", "false").lower() == "true" # Legge l'attributo pk
                        }
                        if col_details["name"] and col_details["start"] is not None and col_details["length"] is not None:
                            columns.append(col_details)
                        else:
                            print(f"Avviso: Dettaglio colonna incompleto per record_type {record_type} saltato.")

                    config["FILE_LAYOUTS"][record_type] = {
                        "target_table": target_table,
                        "schema": schema,
                        "columns": columns
                    }
                else:
                    print("Avviso: Layout con record_type o target_table mancante saltato.")

        # Validazione dei parametri essenziali FTP e Local
        required_ftp = ["FTP_HOST", "FTP_USER", "FTP_PASS"]
        for key in required_ftp:
            if not config.get(key):
                messagebox.showerror("Errore Configurazione", f"Parametro FTP '{key}' mancante o vuoto nel file XML.")
                sys.exit(1)

        return config

    except FileNotFoundError:
        messagebox.showerror("Errore Configurazione", f"File di configurazione '{xml_file_path}' non trovato.")
        sys.exit(1)
    except ET.ParseError as e:
        messagebox.showerror("Errore Configurazione", f"Errore nel parsing del file XML '{xml_file_path}': {e}")
        sys.exit(1)
    except Exception as e:
        messagebox.showerror("Errore Configurazione", f"Errore imprevisto durante il caricamento della configurazione: {e}")
        sys.exit(1)

if __name__ == '__main__':
    # Test di caricamento
    config = load_app_config()
    if config:
        print("Configurazione caricata con successo:")
        for key, value in config.items():
            print(f"  {key}: {value}")
    else:
        print("Caricamento configurazione fallito.")
