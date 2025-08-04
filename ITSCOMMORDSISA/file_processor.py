import os
import shutil
import datetime # Ora usato anche per datetime.date
from decimal import Decimal, InvalidOperation # Per la conversione di decimali
import csv # Added

# --- Invoice Processing Constants & Mappings ---
# Normalize header names from TXT file for robust mapping
# (e.g., lower case, replace spaces with underscores, remove special chars)
def normalize_header(header_name: str) -> str:
    # Also handle "Cod.Rep " specifically due to trailing space in example
    if header_name.strip() == "Cod.Rep":
        return "cod_rep"
    return header_name.lower().replace(' ', '_').replace('.', '').replace('-', '_').strip()

# Mapping from normalized TXT header to a tuple: (target_table_type, db_column_name)
# target_table_type can be 'DOC_TESTA' or 'DOC_RIGHE'
INVOICE_HEADER_TO_DB_COLUMN_MAP = {
    normalize_header("Codice Interlocutore"): ("DOC_TESTA", "CODICE_INTERLOCUTORE"),
    normalize_header("Tipo Documento"): ("DOC_TESTA", "TIPO_DOC"),
    normalize_header("Numero Documento"): ("DOC_TESTA", "NUM_DOC"), # Also used for DOC_RIGHE link
    normalize_header("Data Documento"): ("DOC_TESTA", "DATA_DOC"),

    # NUM_DOC is also part of DOC_RIGHE but will be added from the header data during processing
    normalize_header("Codice Articolo"): ("DOC_RIGHE", "COD_ART"),
    normalize_header("Descrizione Articolo"): ("DOC_RIGHE", "DES"),
    # Using the observed problematic normalized header directly as the key.
    # The original "Quantità" (with à) normalizes to "quantità".
    # The file seems to have a header that normalizes to "quantit�" (with � U+FFFD).
    "quantit\ufffd": ("DOC_RIGHE", "QTA"),
    normalize_header("Tipo Misura"): ("DOC_RIGHE", "TIPO_MIS"),
    normalize_header("Prezzo"): ("DOC_RIGHE", "PREZZO"),
    normalize_header("Sconto 1"): ("DOC_RIGHE", "SCONTO1"),
    normalize_header("Sconto 2"): ("DOC_RIGHE", "SCONTO2"),
    normalize_header("Sconto 3"): ("DOC_RIGHE", "SCONTO3"),
    normalize_header("Prezzo Netto"): ("DOC_RIGHE", "PREZZO_NETTO"),
    normalize_header("S-O = Omaggio/Sconto merce"): ("DOC_RIGHE", "OMAGGIO_SN"),
    normalize_header("Codice Iva"): ("DOC_RIGHE", "COD_IVA"),
    normalize_header("Aliquota Iva"): ("DOC_RIGHE", "ALIQUOTA_IVA"),
    normalize_header("Prezzo di Vendita Consigliato"): ("DOC_RIGHE", "PREZZO_VEND_CONS"),
    normalize_header("Cod.Rep"): ("DOC_RIGHE", "COD_REP"), # Normalized: "cod_rep"
    normalize_header("Reparto"): ("DOC_RIGHE", "REPARTO"),
    normalize_header("EAN1"): ("DOC_RIGHE", "EAN1"),
    normalize_header("EAN2"): ("DOC_RIGHE", "EAN2"),
    normalize_header("EAN3"): ("DOC_RIGHE", "EAN3"),
    normalize_header("EAN4"): ("DOC_RIGHE", "EAN4"),
    normalize_header("EAN5"): ("DOC_RIGHE", "EAN5"),
    normalize_header("EAN6"): ("DOC_RIGHE", "EAN6"),
    normalize_header("EAN7"): ("DOC_RIGHE", "EAN7"),
    normalize_header("EAN8"): ("DOC_RIGHE", "EAN8"),
    normalize_header("EAN9"): ("DOC_RIGHE", "EAN9"),
    normalize_header("EAN10"): ("DOC_RIGHE", "EAN10"),
    normalize_header("Riferimento_Ordine"): ("DOC_RIGHE", "RIF_ORDINE"),
}

# --- Data Conversion Utilities for Invoice Processing ---
def parse_invoice_date(date_str: str) -> datetime.date | None:
    if not date_str or not date_str.strip():
        return None
    try:
        # Assuming date format is dd/mm/yyyy as per example "30/06/2025"
        return datetime.datetime.strptime(date_str.strip(), "%d/%m/%Y").date()
    except ValueError:
        # Log this error or handle as per application's error strategy
        print(f"Warning: Could not parse date string '{date_str}'")
        return None

def parse_invoice_decimal(decimal_str: str) -> Decimal | None:
    if not decimal_str or not decimal_str.strip():
        return None
    try:
        # Standardize by removing thousands separators (dots) and then replacing comma with dot for decimal
        # Example: "1.234,56" -> "1234.56"; "123,45" -> "123.45"
        original_for_debug = decimal_str # For debug
        cleaned_str = decimal_str.strip().replace('.', '') # Remove potential thousands separators
        cleaned_str = cleaned_str.replace(',', '.')     # Replace decimal comma with dot
        print(f"DEBUG parse_invoice_decimal: original='{original_for_debug}', cleaned='{cleaned_str}'") # DEBUG LINE
        return Decimal(cleaned_str)
    except InvalidOperation:
        print(f"Warning: Could not parse decimal string '{original_for_debug}' (cleaned to '{cleaned_str}')")
        return None

def to_nullable_string(value: str | None) -> str | None:
    if value is None:
        return None
    stripped_value = value.strip()
    return stripped_value if stripped_value else None

# --- End of Invoice Processing Utilities ---

# --- LISPRELIEVO CSV Processing Constants & Mappings ---
LISPRELIEVO_CSV_HEADER_MAP = {
    # CSV Header (Normalized) : DB Column Name
    normalize_header("MAGAZZINO"): "MAGAZZ",
    normalize_header("CLIENTE"): "CLI",
    normalize_header("DATA ORDINE"): "DATA_ORD",
    normalize_header("N.LISTA"): "N_LISTA",
    normalize_header("DATA LISTA"): "DATA_LIST",
    normalize_header("CODICE ARTICOLO"): "COD_ART",
    normalize_header("DESCRIZIONE"): "DES",
    normalize_header("EAN"): "EAN",
    normalize_header("COLLI RICHIESTI"): "COLL_RICH",
    normalize_header("COLLI EVASI"): "COLL_EVASI",
    normalize_header("COLLI INEVASI"): "COLL_INEVASI",
    normalize_header("MPL"): "MPL",
    normalize_header("STATO"): "STATO",
    normalize_header("RIFORD"): "RIFORD",
}

# --- Additional Data Conversion Utilities ---
def parse_int(val_str: str | None) -> int | None:
    """
    Parses a string to an integer. Returns None if input is None, empty, whitespace, or invalid.
    """
    if val_str is None or not val_str.strip():
        return None
    try:
        # Assuming integer strings don't have thousands separators that need removal for these fields.
        # If they could (e.g., "1.000"), more cleaning would be needed here.
        return int(val_str.strip())
    except ValueError:
        print(f"Warning: Could not parse integer string '{val_str}'")
        return None

# Note: parse_invoice_date (renamed or aliased if desired) and to_nullable_string
# from Invoice Processing Utilities can be reused for LISPRELIEVO CSVs.
# For clarity, if parse_invoice_date is used, ensure its logic handles "1/07/2025" correctly.
# The current strptime("%d/%m/%Y") handles single digit day/month.

# --- End of LISPRELIEVO CSV Utilities ---


class FileProcessor:
    def __init__(self, local_import_dir, ordine_dir=None, file_prefix="divulgaz"):
        self.local_import_dir = local_import_dir
        self.ordine_dir = ordine_dir
        self.file_prefix = file_prefix

    def process_lisprelievo_csv_file(self, filepath: str) -> list[dict] | None:
        """
        Processes a semicolon-separated CSV file for LISPRELIEVO table.
        Reads headers, maps them to LISPRELIEVO fields,
        parses data, and returns a list of row dictionaries.
        """
        processed_rows = []
        try:
            with open(filepath, "r", encoding='utf-8', errors='replace') as f:
                csv_reader = csv.reader(f, delimiter=';')

                header_row_raw = next(csv_reader, None)
                if not header_row_raw:
                    print(f"Warning: LISPRELIEVO CSV file '{filepath}' is empty or has no header.")
                    return None

                # Strip whitespace from headers then normalize
                normalized_file_headers = [normalize_header(h.strip()) for h in header_row_raw]

                file_header_to_index_map = {header_name: i for i, header_name in enumerate(normalized_file_headers)}

                expected_db_cols_from_map = set(LISPRELIEVO_CSV_HEADER_MAP.values())

                for row_num, data_row_values_original in enumerate(csv_reader, 2):
                    num_expected_fields = len(normalized_file_headers)
                    actual_fields_count = len(data_row_values_original)
                    fields_to_process = data_row_values_original

                    if not data_row_values_original:
                        print(f"Info: Skipping completely empty row {row_num} in LISPRELIEVO CSV '{filepath}'.")
                        continue

                    if actual_fields_count == num_expected_fields + 1 and data_row_values_original[-1].strip() == "":
                        fields_to_process = data_row_values_original[:-1]
                    elif actual_fields_count != num_expected_fields:
                        if not any(field.strip() for field in data_row_values_original):
                            print(f"Info: Skipping effectively empty (all whitespace) row {row_num} in LISPRELIEVO CSV '{filepath}'.")
                            continue
                        print(f"Warning: Skipping malformed row {row_num} in LISPRELIEVO CSV '{filepath}'. Expected {num_expected_fields} columns, got {actual_fields_count}. Data: {data_row_values_original}")
                        continue

                    row_dict = {}
                    for map_key_norm, db_col_name in LISPRELIEVO_CSV_HEADER_MAP.items():
                        raw_value_str = None
                        if map_key_norm in file_header_to_index_map:
                            col_idx = file_header_to_index_map[map_key_norm]
                            if col_idx < len(fields_to_process):
                                raw_value_str = fields_to_process[col_idx].strip() # Strip all data values
                            else:
                                print(f"Warning: Index {col_idx} for header '{map_key_norm}' out of bounds for row {row_num} in LISPRELIEVO CSV '{filepath}'.")
                        # else: A header defined in LISPRELIEVO_CSV_HEADER_MAP was not found in the file. Field will be None.

                        # Apply type conversions
                        if db_col_name in ["DATA_ORD", "DATA_LIST"]:
                            row_dict[db_col_name] = parse_invoice_date(raw_value_str) # Reusing
                        elif db_col_name in ["COLL_RICH", "COLL_EVASI", "COLL_INEVASI"]:
                            row_dict[db_col_name] = parse_int(raw_value_str)
                        else: # Default to nullable string for all other fields
                            row_dict[db_col_name] = to_nullable_string(raw_value_str)

                    # Ensure all DB columns from map are in dict, even if mapped header was missing
                    for db_col_mapped in expected_db_cols_from_map:
                        if db_col_mapped not in row_dict:
                            row_dict[db_col_mapped] = None

                    processed_rows.append(row_dict)

            if not processed_rows:
                print(f"Info: No valid data rows extracted from LISPRELIEVO CSV '{filepath}'.")
                return None

            return processed_rows

        except FileNotFoundError:
            print(f"Error: LISPRELIEVO CSV file not found at '{filepath}'")
            return None
        except csv.Error as e_csv:
            print(f"Error parsing LISPRELIEVO CSV file '{filepath}': {e_csv}")
            return None
        except Exception as e:
            print(f"Error processing LISPRELIEVO CSV file '{filepath}': {e.__class__.__name__} - {e}")
            import traceback
            print(traceback.format_exc())
            return None

    def process_invoice_txt_file(self, filepath: str) -> dict | None:
        self.local_import_dir = local_import_dir
        self.ordine_dir = ordine_dir
        self.file_prefix = file_prefix

    def process_invoice_txt_file(self, filepath: str) -> dict | None:
        """
        Processes a semicolon-separated TXT invoice file.
        Reads headers, maps them to DOC_TESTA and DOC_RIGHE fields,
        parses data, and returns a structured dictionary.
        """
        processed_data = {"doc_testa": [], "doc_righe": []}
        # doc_testa_map stores unique DOC_TESTA records, keyed by NUM_DOC to avoid duplicates
        doc_testa_map = {}

        try:
            with open(filepath, "r", encoding='utf-8', errors='replace') as f:
                csv_reader = csv.reader(f, delimiter=';')

                header_row_raw = next(csv_reader, None)
                if not header_row_raw:
                    print(f"Warning: Invoice file '{filepath}' is empty or has no header.")
                    return None

                # Normalize headers from the file for consistent mapping
                normalized_file_headers = [normalize_header(h) for h in header_row_raw]

                # Create a map of normalized header name from file to its column index
                # print(f"DEBUG Normalized File Headers: {normalized_file_headers}") # DEBUG LINE - REMOVED
                file_header_to_index_map = {header_name: i for i, header_name in enumerate(normalized_file_headers)}

                for row_num, data_row_values_original in enumerate(csv_reader, 2): # row_num starts at 2 (actual line number)

                    num_expected_fields = len(normalized_file_headers)
                    actual_fields_count = len(data_row_values_original)
                    fields_to_process = data_row_values_original

                    if not data_row_values_original: # Completely empty row after potential split
                        print(f"Info: Skipping completely empty row {row_num} in '{filepath}'.")
                        continue

                    # Check for column count mismatches
                    if actual_fields_count == num_expected_fields + 1:
                        # If there's one extra column, assume it's extraneous (e.g. trailing delimiter or an unmapped field)
                        # Log if the extra column contains data, then proceed with the expected number of fields.
                        if data_row_values_original[-1].strip() != "":
                            print(f"Info: Row {row_num} in '{filepath}' has {actual_fields_count} columns, expected {num_expected_fields}. Extra non-empty data in last column ('{data_row_values_original[-1]}') will be ignored.")
                        else:
                            print(f"Info: Row {row_num} in '{filepath}' has an extra empty column, likely due to a trailing delimiter. Ignoring it.")
                        fields_to_process = data_row_values_original[:-1] # Take the first N fields
                    elif actual_fields_count != num_expected_fields:
                        # If it's any other mismatch, check if the row is effectively empty
                        if not any(field.strip() for field in data_row_values_original):
                            print(f"Info: Skipping effectively empty (all whitespace) row {row_num} in '{filepath}'.")
                            continue
                        # Otherwise, it's a more significant malformation
                        print(f"Warning: Skipping malformed row {row_num} in '{filepath}'. Expected {num_expected_fields} columns, got {actual_fields_count}. Data: {data_row_values_original}")
                        continue
                    # else: actual_fields_count == num_expected_fields, so fields_to_process is data_row_values_original

                    # Build a dictionary for the current row using normalized headers from the file
                    # and the (potentially adjusted) fields_to_process
                    current_row_dict_raw = {}
                    for i, val in enumerate(fields_to_process):
                        # Ensure we don't go out of bounds for normalized_file_headers if fields_to_process was not adjusted
                        # This should ideally not happen if the logic above is correct
                        if i < len(normalized_file_headers):
                             current_row_dict_raw[normalized_file_headers[i]] = val
                        else:
                            # This case indicates a logic flaw or unexpected data scenario
                            print(f"Error: Field index {i} out of bounds for headers at row {row_num} in '{filepath}'. This should not happen.")
                            break # Stop processing this row

                    if len(current_row_dict_raw) != num_expected_fields : # If the above break happened
                        continue


                    # --- Extract NUM_DOC first, as it's critical ---
                    num_doc_txt_normalized_header = normalize_header("Numero Documento") # This is "numero_documento"
                    num_doc_val_str = current_row_dict_raw.get(num_doc_txt_normalized_header)
                    num_doc_db_val = to_nullable_string(num_doc_val_str)

                    if not num_doc_db_val:
                        print(f"Warning: Skipping row {row_num} in '{filepath}' due to missing or empty 'Numero Documento'.")
                        continue

                    # --- Process for DOC_TESTA ---
                    # Create a DOC_TESTA entry only if this NUM_DOC hasn't been processed yet
                    if num_doc_db_val not in doc_testa_map:
                        temp_doc_testa_entry = {"NUM_DOC": num_doc_db_val} # Initialize with the key
                        for map_norm_header, (target_type, db_col) in INVOICE_HEADER_TO_DB_COLUMN_MAP.items():
                            # DEBUG: Print all map entries for inspection if needed
                            # print(f"DEBUG MAP Scanning: map_norm_header='{map_norm_header}', target='{target_type}', db_col='{db_col}'")
                            if target_type == "DOC_TESTA":
                                if map_norm_header in current_row_dict_raw: # Check if the header exists in the file
                                    raw_value_from_file = current_row_dict_raw[map_norm_header]
                                    if db_col == "DATA_DOC":
                                        temp_doc_testa_entry[db_col] = parse_invoice_date(raw_value_from_file)
                                    # NUM_DOC is already handled
                                    elif db_col != "NUM_DOC": # other DOC_TESTA string fields
                                        temp_doc_testa_entry[db_col] = to_nullable_string(raw_value_from_file)
                                else: # Header from map not found in file for DOC_TESTA
                                     if db_col not in temp_doc_testa_entry : temp_doc_testa_entry[db_col] = None


                        # Ensure all required DOC_TESTA fields are present, even if None
                        for _, db_col_name_testa in filter(lambda item: item[1][0] == "DOC_TESTA", INVOICE_HEADER_TO_DB_COLUMN_MAP.items()):
                             if db_col_name_testa not in temp_doc_testa_entry: temp_doc_testa_entry[db_col_name_testa] = None

                        doc_testa_map[num_doc_db_val] = temp_doc_testa_entry

                    # --- Process for DOC_RIGHE ---
                    temp_doc_riga_entry = {"NUM_DOC": num_doc_db_val} # Link to the header

                    for map_norm_header, (target_type, db_col) in INVOICE_HEADER_TO_DB_COLUMN_MAP.items():
                        if target_type == "DOC_RIGHE":
                            if map_norm_header in current_row_dict_raw: # Check if the header exists in the file
                                raw_value_from_file = current_row_dict_raw[map_norm_header]
                                if db_col in ["QTA", "PREZZO", "SCONTO1", "SCONTO2", "SCONTO3", "PREZZO_NETTO", "ALIQUOTA_IVA", "PREZZO_VEND_CONS"]:
                                    parsed_val = parse_invoice_decimal(raw_value_from_file)
                                    if parsed_val is not None:
                                        # Apply specific rounding based on DB schema
                                        if db_col == 'QTA':
                                            # decimal(15, 3)
                                            temp_doc_riga_entry[db_col] = parsed_val.quantize(Decimal('0.001'))
                                        elif db_col in ['SCONTO1', 'SCONTO2', 'SCONTO3', 'ALIQUOTA_IVA']:
                                            # decimal(5, 2)
                                            temp_doc_riga_entry[db_col] = parsed_val.quantize(Decimal('0.01'))
                                        else: # PREZZO, PREZZO_NETTO, PREZZO_VEND_CONS
                                            # decimal(15, 4)
                                            temp_doc_riga_entry[db_col] = parsed_val.quantize(Decimal('0.0001'))
                                    else:
                                        temp_doc_riga_entry[db_col] = None
                                else: # All other DOC_RIGHE fields are treated as strings or nullable strings
                                    temp_doc_riga_entry[db_col] = to_nullable_string(raw_value_from_file)
                            else: # Header from map not found in file for DOC_RIGHE
                                if db_col not in temp_doc_riga_entry: temp_doc_riga_entry[db_col] = None

                    # Ensure all DOC_RIGHE fields are present
                    for _, db_col_name_righe in filter(lambda item: item[1][0] == "DOC_RIGHE", INVOICE_HEADER_TO_DB_COLUMN_MAP.items()):
                        if db_col_name_righe not in temp_doc_riga_entry: temp_doc_riga_entry[db_col_name_righe] = None

                    processed_data["doc_righe"].append(temp_doc_riga_entry)

            # Convert doc_testa_map values to a list for the final output
            original_doc_testa_list = list(doc_testa_map.values())

            # --- Sanitize final dictionaries to ensure only expected string keys ---
            final_doc_testa_list = []
            expected_testa_cols = {db_col for _norm_h, (tt, db_col) in INVOICE_HEADER_TO_DB_COLUMN_MAP.items() if tt == "DOC_TESTA"}
            for testa_entry_original in original_doc_testa_list:
                sanitized_entry = {}
                for col in expected_testa_cols: # Iterate over expected DB columns
                    sanitized_entry[col] = testa_entry_original.get(col) # Get value if key exists, else None
                final_doc_testa_list.append(sanitized_entry)
            processed_data["doc_testa"] = final_doc_testa_list

            final_doc_righe_list = []
            expected_righe_cols = {db_col for _norm_h, (tt, db_col) in INVOICE_HEADER_TO_DB_COLUMN_MAP.items() if tt == "DOC_RIGHE"}
            expected_righe_cols.add("NUM_DOC") # NUM_DOC is manually added to righe entries

            for riga_entry_original in processed_data["doc_righe"]:
                sanitized_entry = {}
                for col in expected_righe_cols: # Iterate over expected DB columns
                    val_to_sanitize = riga_entry_original.get(col)
                    sanitized_entry[col] = val_to_sanitize
                    # if col == "QTA": # DEBUG FOR QTA - REMOVED
                    #     print(f"DEBUG QTA Sanitization: riga_entry_original.get('QTA')='{val_to_sanitize}', type='{type(val_to_sanitize)}', sanitized_entry['QTA']='{sanitized_entry[col]}'")
                final_doc_righe_list.append(sanitized_entry)
            processed_data["doc_righe"] = final_doc_righe_list
            # --- End Sanitization ---

            if not processed_data["doc_testa"] and not processed_data["doc_righe"]:
                print(f"Info: No valid data extracted from invoice file '{filepath}'. File might be empty after header or all rows had critical issues.")
                return None

            return processed_data

        except FileNotFoundError:
            print(f"Error: Invoice file not found at '{filepath}'")
            return None
        except csv.Error as e_csv:
            print(f"Error parsing CSV in invoice file '{filepath}': {e_csv}")
            return None
        except Exception as e:
            print(f"Error processing invoice file '{filepath}': {e.__class__.__name__} - {e}")
            import traceback
            print(traceback.format_exc()) # Print full traceback for unexpected errors
            return None

    def ensure_local_import_dir_exists(self): # Original method, ensure it's not duplicated by mistake
        """
        Assicura che LOCAL_IMPORT_DIR esista e sia scrivibile.
        Ritorna True se ok, False e un messaggio d'errore altrimenti.
        """
        try:
            if not os.path.exists(self.local_import_dir):
                os.makedirs(self.local_import_dir, exist_ok=True)

            test_file = os.path.join(self.local_import_dir, ".tmp_write_test_import")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            return True, f"Directory di importazione locale '{self.local_import_dir}' pronta."
        except Exception as e:
            return False, f"Impossibile creare o scrivere su '{self.local_import_dir}': {e}"

    def ensure_ordine_dir_exists(self):
        """
        Assicura che ORDINE_DIR esista, se configurata.
        Ritorna True se ok o non configurata, False e un messaggio d'errore se fallisce la creazione.
        """
        if not self.ordine_dir:
            return True, "ORDINE_DIR non configurata, creazione saltata."
        try:
            os.makedirs(self.ordine_dir, exist_ok=True)

            # Create Save and LOG subdirectories
            save_dir = os.path.join(self.ordine_dir, "Save")
            log_dir = os.path.join(self.ordine_dir, "LOG")
            os.makedirs(save_dir, exist_ok=True)
            os.makedirs(log_dir, exist_ok=True)

            return True, f"Directory Ordine '{self.ordine_dir}' e sottodirectory 'Save', 'LOG' pronte."
        except Exception as e:
            return False, f"Errore critico con directory ORDINE_DIR '{self.ordine_dir}' o sue sottodirectory: {e}"

    def process_downloaded_file(self, original_filename, downloaded_filepath):
        """
        Processa un file scaricato: attualmente solo copia in ORDINE_DIR se configurato.
        'downloaded_filepath' è il percorso completo del file come è stato scaricato in LOCAL_IMPORT_DIR
        (già con prefisso).
        Ritorna (True/False per successo generale, messaggio, percorso_file_rinominato_in_import_dir).
        """
        renamed_filepath_in_import_dir = downloaded_filepath
        renamed_filename = os.path.basename(renamed_filepath_in_import_dir)

        overall_success = True
        messages = []

        if self.ordine_dir:
            success_ordine_dir, msg_ordine_dir = self.ensure_ordine_dir_exists()
            if not success_ordine_dir:
                messages.append(f"Copia in ORDINE_DIR fallita (creazione dir): {msg_ordine_dir}")
                overall_success = False # Consideriamo questo un fallimento se la copia era prevista
            else:
                try:
                    dest_path_ordine_dir = os.path.join(self.ordine_dir, renamed_filename)
                    shutil.copy2(renamed_filepath_in_import_dir, dest_path_ordine_dir)
                    messages.append(f"Copiato: {renamed_filename} → {self.ordine_dir}")
                except Exception as e_copy:
                    messages.append(f"Errore copia {renamed_filename} → {self.ordine_dir}: {e_copy}")
                    overall_success = False
        else:
            messages.append("Nessuna copia in ORDINE_DIR configurata.")

        return overall_success, " | ".join(messages), renamed_filepath_in_import_dir

    def _parse_fixed_width_line(self, line, column_layout):
        parsed_data = {}
        for col_def in column_layout:
            # DEBUG log for column definition being processed
            print(f"DEBUG_COL_DEF: Processing column: Name='{col_def.get('name')}', Type='{col_def.get('type')}', Format='{col_def.get('format')}'")
            name = col_def["name"]
            start = col_def["start"] - 1
            length = col_def["length"]
            col_type = col_def.get("type", "str")
            scale = col_def.get("scale")
            decimal_char = col_def.get("decimal_char")
            source_format = col_def.get("source_format") # Corrected key name

            if start + length > len(line):
                parsed_data[name] = None
                continue

            raw_value = line[start : start + length].strip()

            if not raw_value:
                parsed_data[name] = None
                continue

            try:
                if col_type == "str":
                    parsed_data[name] = raw_value
                elif col_type == "int":
                    parsed_data[name] = int(raw_value)
                elif col_type == "decimal":
                    if decimal_char:
                        raw_value = raw_value.replace(decimal_char, '.')
                    val = Decimal(raw_value)
                    if scale is not None and not decimal_char and raw_value.isdigit(): # Impliciti decimali
                         val = val / (10**scale)
                    parsed_data[name] = val
                elif col_type == "str_date":
                    if source_format == "aammgg":
                        # Handle special placeholder dates first
                        if raw_value in ["999999", "000000"]:
                            parsed_data[name] = None
                            print(f"DEBUG_DATE_PARSE: field='{name}', raw='{raw_value}', outcome='None' (special placeholder)")
                        elif not raw_value: # Empty string for a date field
                             parsed_data[name] = None
                             print(f"DEBUG_DATE_PARSE: field='{name}', raw='{raw_value}', outcome='None' (empty string)")
                        elif len(raw_value) == 6 and raw_value.isdigit():
                            print(f"DEBUG_DATE_PARSE: field='{name}', raw='{raw_value}', attempting to parse...")
                            year_str = raw_value[0:2]
                            month_str = raw_value[2:4]
                            day_str = raw_value[4:6]

                            year_int = int(year_str)
                            full_year = (2000 + year_int) if year_int < 70 else (1900 + year_int) # Y2K

                            month_int = int(month_str)
                            day_int = int(day_str)

                            if not (1 <= month_int <= 12):
                                raise ValueError(f"Mese non valido '{month_str}' in data AAMMGG: '{raw_value}'")
                            if not (1 <= day_int <= 31):
                                raise ValueError(f"Giorno non valido '{day_str}' in data AAMMGG: '{raw_value}'")

                            parsed_data[name] = datetime.date(full_year, month_int, day_int)
                            print(f"DEBUG_DATE_PARSE: field='{name}', parsed_value='{parsed_data[name]}', type='{type(parsed_data[name])}'")
                        else:
                            # This case means raw_value is not a placeholder, not empty, but not 6 digits.
                            raise ValueError(f"Formato data AAMMGG non valido o stringa non numerica/non 6 cifre: '{raw_value}'")
                    else: # Altri formati di data stringa non gestiti specificamente
                        parsed_data[name] = raw_value
                else:
                    parsed_data[name] = raw_value
            except ValueError as ve:
                raise ValueError(f"Errore conversione campo '{name}' val='{raw_value}' tipo='{col_type}': {ve}")
            except InvalidOperation as ioe:
                raise ValueError(f"Errore Decimal campo '{name}' val='{raw_value}': {ioe}")
        return parsed_data

    def get_db_error_log_path(self):
        log_dir = self.ordine_dir if self.ordine_dir and os.path.exists(self.ordine_dir) else self.local_import_dir
        if log_dir and os.path.exists(log_dir): # Assicura che anche local_import_dir esista
             # Crea la directory di log se non esiste (es. se ordine_dir non era ancora stato creato)
            os.makedirs(log_dir, exist_ok=True)
            return os.path.join(log_dir, "import_db_errors.log")
        # Fallback a directory corrente se nessuna delle due è valida (improbabile)
        print(f"Attenzione: directory di log non valida ({self.ordine_dir} o {self.local_import_dir}). Log in directory corrente.")
        return os.path.join(os.path.abspath("."), "import_db_errors.log")


    def log_db_error(self, filename, line_number, record_type, error_message):
        log_path = self.get_db_error_log_path()
        print(f"DEBUG FILE_PROC: Tentativo di loggare su '{log_path}'. Messaggio: '{error_message}'") # DEBUG
        if not log_path:
            print("DEBUG FILE_PROC: Percorso di log DB non valido (None), impossibile loggare.") # DEBUG
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} - File: {filename}, Riga/Info: {line_number}, TipoRecord: {record_type}, Errore: {error_message}\n"
        try:
            with open(log_path, "a", encoding='utf-8') as f:
                f.write(log_entry)
            print(f"DEBUG FILE_PROC: Messaggio loggato con successo in {log_path}") # DEBUG
        except Exception as e:
            print(f"ERRORE CRITICO SCRITTURA LOG DB: Impossibile scrivere nel file di log DB {log_path}: {e}")


    def process_file_for_db_import(self, filepath, file_layouts_config):
        if not os.path.exists(filepath):
            return None, [f"File non trovato: {filepath}"]

        filename = os.path.basename(filepath)
        parsed_data_by_record_type = {}
        parsing_errors = []

        # New structures for PRODOTTI_FOR logic
        current_file_anafor_map = {}
        parsed_prodotti_for_direct = []
        anarti_needing_anafor_db_lookup = []

        try:
            with open(filepath, "r", encoding='utf-8', errors='replace') as f:
                for line_num, line_content in enumerate(f, 1):
                    line = line_content.rstrip('\r\n')
                    if not line.strip():
                        continue

                    record_type_from_file = line[:6].strip().upper()
                    layout = file_layouts_config.get(record_type_from_file)

                    if not layout:
                        error_msg = f"Riga {line_num}: Tipo record '{record_type_from_file}' non definito nei layout XML."
                        parsing_errors.append(error_msg)
                        continue

                    try:
                        # Parsed_row_data_dict contains the raw parsed data for the current line
                        parsed_row_data_dict = self._parse_fixed_width_line(line, layout["columns"])
                        if parsed_row_data_dict is None:
                            error_msg = f"Riga {line_num}: Riga troppo corta o malformata per il parsing completo."
                            parsing_errors.append(error_msg)
                            continue

                        # Initialize structure for this record type if first time seen
                        if record_type_from_file not in parsed_data_by_record_type:
                            col_names = [col_def["name"] for col_def in layout["columns"]]
                            if record_type_from_file == "ANARTI":
                                col_names.extend(["COD_SISA", "DES_COD_SISA"]) # Augment ANARTI cols

                            parsed_data_by_record_type[record_type_from_file] = {
                                "schema": layout["schema"],
                                "target_table": layout["target_table"],
                                "col_names": col_names,
                                "rows_values": [] # List of tuples for DBImporter
                            }

                        # Create a mutable copy of parsed_row_data_dict for potential modifications (e.g. ANARTI fixed values)
                        # This dict (current_record_as_dict) will be used for PRODOTTI_FOR logic and then converted to tuple for standard import
                        current_record_as_dict = parsed_row_data_dict.copy()

                        if record_type_from_file == "ANARTI":
                            current_record_as_dict["COD_SISA"] = 999999
                            current_record_as_dict["DES_COD_SISA"] = "Europa Commerciale S.r.l."

                        # Convert the (potentially modified) dict to a tuple of values for standard import path
                        # This uses the col_names defined for this record_type_from_file (which are augmented for ANARTI)
                        current_row_values_tuple = []
                        for col_name_in_order in parsed_data_by_record_type[record_type_from_file]["col_names"]:
                            current_row_values_tuple.append(current_record_as_dict.get(col_name_in_order))

                        # --- Focused Debug for VARLIS before appending ---
                        if record_type_from_file == "VARLIS":
                            print(f"DEBUG_FP_VARLIS_TUPLE: Record Type: {record_type_from_file}")
                            print(f"DEBUG_FP_VARLIS_TUPLE: Col Names: {parsed_data_by_record_type[record_type_from_file]['col_names']}")
                            # Create the tuple for logging, same as what will be appended
                            final_tuple_to_append = tuple(current_row_values_tuple)
                            print(f"DEBUG_FP_VARLIS_TUPLE: Row Tuple to be appended: {final_tuple_to_append}")
                            for i, val in enumerate(final_tuple_to_append):
                                print(f"DEBUG_FP_VARLIS_TUPLE: Index {i}, Value: '{val}', Type: {type(val)}")
                        # --- End Focused Debug ---

                        parsed_data_by_record_type[record_type_from_file]["rows_values"].append(tuple(current_row_values_tuple))

                        # --- PRODOTTI_FOR specific logic ---
                        if record_type_from_file == "ANAFOR":
                            cod_forni_key = current_record_as_dict.get("COD_FORNI")
                            if cod_forni_key is not None: # Should always be there for ANAFOR
                                current_file_anafor_map[str(cod_forni_key).strip()] = current_record_as_dict

                        elif record_type_from_file == "ANARTI":
                            # current_record_as_dict for ANARTI already includes COD_SISA, DES_COD_SISA
                            ult_cod_forni_val = current_record_as_dict.get("ULT_COD_FORNI")
                            if ult_cod_forni_val is not None:
                                ult_cod_forni_key = str(ult_cod_forni_val).strip()
                                if ult_cod_forni_key in current_file_anafor_map:
                                    anafor_file_record_data = current_file_anafor_map[ult_cod_forni_key]

                                    # Construct PRODOTTI_FOR record dictionary (DATA_AGG set later)
                                    # P_IVA_FORNI comes from ANARTI record
                                    prod_for_dict = {
                                        "COD_ART": current_record_as_dict.get("COD_ART"),
                                        "COD_EAN_ULT_INS": current_record_as_dict.get("COD_EAN_ULT_INS"),
                                        "DES": current_record_as_dict.get("DES"),
                                        "UN_MIS": current_record_as_dict.get("UN_MIS"),
                                        "TIPO_UN_MIS": current_record_as_dict.get("TIPO_UN_MIS"),
                                        "COD_FORNI": ult_cod_forni_val, # This will need to be INT later
                                        "P_IVA_FORNI": current_record_as_dict.get("P_IVA_FORNI"), # From ANARTI
                                        "RAGSOC": anafor_file_record_data.get("RAGSOC"),
                                        "INDIRIZZO": anafor_file_record_data.get("INDIRIZZO"),
                                        "LOCALITA": anafor_file_record_data.get("LOCALITA"),
                                        "PROV": anafor_file_record_data.get("PROV"),
                                        "CAP": anafor_file_record_data.get("CAP"),
                                        "TEL": anafor_file_record_data.get("TEL"),
                                        "FAX": anafor_file_record_data.get("FAX"),
                                        "EMAIL": anafor_file_record_data.get("EMAIL"),
                                        "COD_ART_FORNI_1": current_record_as_dict.get("COD_ART_FORNI_1"),
                                        "COD_ART_FORNI_2": current_record_as_dict.get("COD_ART_FORNI_2"),
                                        "COD_ART_FORNI_3": current_record_as_dict.get("COD_ART_FORNI_3"),
                                        "AREA": current_record_as_dict.get("AREA"),
                                        "SETTORE": current_record_as_dict.get("SETTORE"),
                                        "COMPARTO": current_record_as_dict.get("COMPARTO"),
                                        "FAM": current_record_as_dict.get("FAM"),
                                        "SUB_FAM": current_record_as_dict.get("SUB_FAM"),
                                        "AL_IVA": current_record_as_dict.get("AL_IVA"),
                                        "STATO_ART": current_record_as_dict.get("STATO_ART"),
                                        "IMB": current_record_as_dict.get("IMB"),
                                        "PZ_X_CART": current_record_as_dict.get("PZ_X_CART"),
                                        "CART_X_PALLET": current_record_as_dict.get("CART_X_PALLET"),
                                        "GEST_POS": current_record_as_dict.get("GEST_POS"),
                                        "LEGAME": current_record_as_dict.get("LEGAME"),
                                        "FASC_APP": current_record_as_dict.get("FASC_APP"),
                                        "REP_CASSA": current_record_as_dict.get("REP_CASSA"),
                                        "PLU": current_record_as_dict.get("PLU"),
                                        "ASSORT_SN": current_record_as_dict.get("ASSORT_SN"),
                                        # DATA_AGG will be added later before DB import
                                    }
                                    parsed_prodotti_for_direct.append(prod_for_dict)
                                else:
                                    # ANAFOR not found in current file, add ANARTI record for DB lookup
                                    anarti_needing_anafor_db_lookup.append(current_record_as_dict)
                            else: # ULT_COD_FORNI is None in ANARTI record
                                # Decide if this ANARTI record should also be checked against DB for ANAFOR,
                                # or if it's an error, or if it simply doesn't participate in PRODOTTI_FOR.
                                # For now, let's assume if ULT_COD_FORNI is None, it doesn't go to PRODOTTI_FOR.
                                pass # Or log a warning if ULT_COD_FORNI is expected.

                    except ValueError as ve:
                        error_msg = f"Riga {line_num} ({record_type_from_file}): Errore parsing/conversione: {ve}"
                        parsing_errors.append(error_msg)
                    except Exception as e_parse:
                        error_msg = f"Riga {line_num} ({record_type_from_file}): Errore parsing imprevisto: {e_parse}"
                        parsing_errors.append(error_msg)

        except FileNotFoundError:
            # Return all three data structures even in case of file not found, they will be empty.
            return None, [], [], [f"File non trovato: {filepath}"]
        except Exception as e_file_read:
            return None, [], [], [f"Errore lettura file {filepath}: {e_file_read}"]

        return parsed_data_by_record_type, parsed_prodotti_for_direct, anarti_needing_anafor_db_lookup, parsing_errors

    # --- New Logging Methods ---
    def get_log_filepath(self, log_type: str) -> str | None:
        """Determines the filepath for a specific log type (e.g., '730_fixed', 'TXT_invoice')."""
        log_dir_base = self.ordine_dir if self.ordine_dir else self.local_import_dir

        if not log_dir_base:
            # This case should ideally be handled by ensuring one of these dirs is always valid if logging is expected
            print(f"Warning: Base directory for logging (ORDINE_DIR or LOCAL_IMPORT_DIR) not available for log_type '{log_type}'.")
            # Fallback to current working directory's LOG subdir if no base configured.
            # This is a last resort and indicates a potential configuration issue.
            log_dir_base = os.path.abspath(".")
            print(f"Fallback: Attempting to use LOG subdir in current working directory: {log_dir_base}")


        log_subdir = os.path.join(log_dir_base, "LOG")
        try:
            # Ensure LOG subdirectory exists, create if not.
            # This was also done in ensure_ordine_dir_exists, but good to have fallback here.
            if not os.path.exists(log_subdir):
                 os.makedirs(log_subdir, exist_ok=True)
        except Exception as e:
            print(f"ERROR: Could not create LOG subdirectory at '{log_subdir}': {e}. Will attempt to log in base directory '{log_dir_base}'.")
            log_subdir = log_dir_base # Fallback to log_dir_base itself if LOG subdir creation fails

        today_str = datetime.datetime.now().strftime("%Y%m%d")
        # Sanitize log_type for filename (e.g. replace spaces, slashes)
        safe_log_type = log_type.replace(" ", "_").replace("/", "_").replace("\\", "_")
        log_filename = f"{today_str}_import_{safe_log_type}.log"

        final_log_path = os.path.join(log_subdir, log_filename)
        # print(f"DEBUG get_log_filepath: Determined log path: {final_log_path}") # Optional debug
        return final_log_path

    def log_import_details(self, log_type: str, source_filename: str, status: str,
                           records_attempted: int = 0, records_succeeded: int = 0,
                           error_details: list[str] = None, other_info: str = None):
        """
        Logs detailed information about a file's import process to a specific log file.
        """
        log_filepath = self.get_log_filepath(log_type)
        if not log_filepath:
            print(f"CRITICAL: Log filepath could not be determined for log_type '{log_type}'. Logging skipped for {source_filename}.")
            # Potentially log this critical failure to a default fallback log, e.g., in app's execution dir
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Use a list to build log entry for easier multi-line formatting
        log_entry_parts = [
            f"--- Log Entry Start: {timestamp} ---",
            f"File Processed   : {source_filename}",
            f"Overall Status   : {status}",
        ]
        if status not in ["SKIPPED_FILE_NOT_FOUND", "SKIPPED_EMPTY_OR_NO_HEADER"]: # Only show counts if processing was attempted
            log_entry_parts.extend([
                f"Records Attempted: {records_attempted}",
                f"Records Succeeded: {records_succeeded}",
                f"Records Failed   : {records_attempted - records_succeeded}",
            ])

        if other_info:
            log_entry_parts.append(f"Additional Info  : {other_info.strip()}")

        # Handle error messages
        actual_error_messages = error_details if error_details is not None else []
        if actual_error_messages:
            log_entry_parts.append("Error Details    :")
            for i, err_msg in enumerate(actual_error_messages):
                # Indent error messages for readability, handle multi-line errors gracefully
                indented_err_msg = "\n                   ".join(err_msg.strip().splitlines())
                log_entry_parts.append(f"  - Error {i+1:03d}    : {indented_err_msg}")
        elif status not in ["SUCCESS", "SKIPPED_ALL_EXISTING", "SKIPPED_FILE_NOT_FOUND", "SKIPPED_EMPTY_OR_NO_HEADER"] and (records_attempted - records_succeeded > 0) :
             log_entry_parts.append("Error Details    : No specific error messages provided, but status or counts indicate issues.")

        log_entry_parts.append(f"--- Log Entry End: {timestamp} ---\n") # Extra newline for spacing

        log_entry_string = "\n".join(log_entry_parts)

        try:
            with open(log_filepath, "a", encoding='utf-8') as f:
                f.write(log_entry_string + "\n") # Ensure newline after entry
        except Exception as e:
            print(f"CRITICAL: Failed to write to log file '{log_filepath}' for {source_filename}: {e}")
            # Fallback: Print to console if file logging fails
            print("--- CONSOLE FALLBACK LOG (due to file write error) ---")
            print(log_entry_string)
            print("--- END CONSOLE FALLBACK LOG ---")

# Esempio di utilizzo:
if __name__ == '__main__':
    # Creare directory di test
    if not os.path.exists("./test_import_dir"): os.makedirs("./test_import_dir")
    if not os.path.exists("./test_ordine_dir"): os.makedirs("./test_ordine_dir")

    processor = FileProcessor("./test_import_dir", "./test_ordine_dir")
    processor_no_ordine = FileProcessor("./test_import_dir")

    # Test ensure_local_import_dir_exists
    ok, msg = processor.ensure_local_import_dir_exists()
    print(f"Ensure Local Import Dir: {ok} - {msg}")

    # Test ensure_ordine_dir_exists
    ok, msg = processor.ensure_ordine_dir_exists()
    print(f"Ensure Ordine Dir: {ok} - {msg}")

    # Simula un file scaricato
    simulated_original_filename = "testfile1.txt"
    simulated_downloaded_path = os.path.join(processor.local_import_dir, f"{processor.file_prefix}{simulated_original_filename}")
    with open(simulated_downloaded_path, "w") as f:
        f.write("Questo è un file di test.\nRiga 2.")

    print(f"\nProcessando file: {simulated_downloaded_path}")
    success, message, processed_path = processor.process_downloaded_file(simulated_original_filename, simulated_downloaded_path)
    print(f"Risultato process_downloaded_file: Successo={success}, Messaggio='{message}', Path='{processed_path}'")

    if success and processor.ordine_dir and os.path.exists(os.path.join(processor.ordine_dir, f"{processor.file_prefix}{simulated_original_filename}")):
        print(f"File {processor.file_prefix}{simulated_original_filename} copiato correttamente in {processor.ordine_dir}")
    elif success and processor.ordine_dir :
        print(f"ATTENZIONE: File non trovato in ORDINE_DIR o errore durante la copia non segnalato come fallimento.")

    # Test con ORDINE_DIR non configurato
    simulated_downloaded_path_2 = os.path.join(processor_no_ordine.local_import_dir, f"{processor.file_prefix}testfile2.txt")
    with open(simulated_downloaded_path_2, "w") as f:
        f.write("File di test 2.")

    print(f"\nProcessando file (senza ORDINE_DIR): {simulated_downloaded_path_2}")
    success, message, processed_path = processor_no_ordine.process_downloaded_file("testfile2.txt", simulated_downloaded_path_2)
    print(f"Risultato process_downloaded_file (no ORDINE_DIR): Successo={success}, Messaggio='{message}', Path='{processed_path}'")


    # Test per process_file_for_db_import
    mock_layouts = {
        "ANARTI": {
            "target_table": "ANARTI", "schema": "dbo",
            "columns": [
                {"name": "COD_ART", "start": 7, "length": 9, "type": "str"},
                {"name": "DES", "start": 16, "length": 10, "type": "str"}
            ]
        }
    }
    test_db_file_content = "ANARTI123456789DESCRIZIONE1\nANARTI987654321DESCRIZIONE2"
    test_db_filepath = os.path.join(processor.ordine_dir or processor.local_import_dir, "test_db_import.txt")
    with open(test_db_filepath, "w") as f:
        f.write(test_db_file_content)

    print(f"\nTest process_file_for_db_import per {test_db_filepath}")
    parsed_data, parsing_errs = processor.process_file_for_db_import(test_db_filepath, mock_layouts)

    if parsing_errs:
        print("Errori di parsing:")
        for err in parsing_errs:
            print(f"  - {err}")
    if parsed_data:
        print("Dati parsati per DB:")
        for rec_type, data in parsed_data.items():
            print(f"  Record Type: {rec_type}")
            print(f"    Target: {data['schema']}.{data['target_table']}")
            print(f"    Colonne: {data['col_names']}")
            print(f"    Righe: {data['rows_values']}")

    # Test log_db_error
    print("\nTest log_db_error...")
    processor.log_db_error("test_file.txt", 10, "ANARTI", "Questo è un errore di test DB.")
    log_file = processor.get_db_error_log_path()
    if log_file and os.path.exists(log_file):
        print(f"Controlla il file di log: {log_file}")
        # with open(log_file, "r") as lf: print(lf.read()) # Opzionale: stampa contenuto log
    else:
        print(f"File di log non creato o percorso non valido: {log_file}")


    # Pulizia (opzionale)
    # if os.path.exists("./test_import_dir"): shutil.rmtree("./test_import_dir")
    # if os.path.exists("./test_ordine_dir"): shutil.rmtree("./test_ordine_dir")
    # if log_file and os.path.exists(log_file): os.remove(log_file)
    print("\nTest del FileProcessor completati.")
