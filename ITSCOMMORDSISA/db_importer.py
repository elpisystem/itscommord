import pyodbc
import datetime # Added for isinstance check
from decimal import Decimal

class DBImporter:
    def __init__(self, driver, server, database_name, username, password):
        self.driver = driver
        self.server = server
        self.database_name = database_name
        self.username = username
        self.password = password

        self.conn_str = (
            f"DRIVER={self.driver};"
            f"SERVER={self.server};"
            f"DATABASE={self.database_name};"
            f"UID={self.username};"
            f"PWD={self.password};"
            # "TrustServerCertificate=yes;" # Opzionale
        )
        self.conn = None
        self.cursor = None

    def connect(self):
        print(f"DEBUG DBIMPORTER: Tentativo di connessione con DRIVER='{self.driver}'")
        print(f"DEBUG DBIMPORTER: Stringa di connessione completa: {self.conn_str}")
        try:
            self.conn = pyodbc.connect(self.conn_str, autocommit=False)
            self.cursor = self.conn.cursor()
            return True, None
        except pyodbc.Error as ex:
            sqlstate = ex.args[0]
            return False, f"Errore connessione DB ({sqlstate}): {ex}"
        except Exception as e:
            return False, f"Errore connessione DB imprevisto: {e}"

    def disconnect(self):
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        if self.conn:
            try:
                self.conn.close()
            except pyodbc.Error as e:
                print(f"DBImporter: Errore durante la chiusura della connessione: {e}")
            finally:
                self.conn = None

    def table_exists(self, table_name, schema='dbo'):
        if not self.conn or not self.cursor:
            return False, "DB non connesso."
        try:
            query = f"SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?"
            self.cursor.execute(query, schema, table_name)
            return self.cursor.fetchone()[0] == 1, None
        except pyodbc.Error as e:
            return False, f"Errore verifica esistenza tabella {schema}.{table_name}: {e}"

    def upsert_data_batch(self, table_name, data_rows, all_column_names, pk_column_names, schema='dbo'):
        print(f"DEBUG DBIMPORTER: INIZIO upsert_data_batch per Tabella: {schema}.{table_name}, PKs: {pk_column_names}, Righe da processare: {len(data_rows)}")

        if not self.conn or not self.cursor:
            return 0, ["DB non connesso."]
        if not data_rows:
            print(f"DEBUG DBIMPORTER: Nessuna riga fornita per {schema}.{table_name}.")
            return 0, []
        if not all_column_names or not isinstance(all_column_names, (list, tuple)) or len(all_column_names) == 0:
            return 0, [f"Lista nomi colonne vuota/invalida per {schema}.{table_name}."]
        if not pk_column_names or not all(pk_col in all_column_names for pk_col in pk_column_names):
             return 0, [f"Nomi colonne PK ({pk_column_names}) non validi o non presenti in all_column_names ({all_column_names}) per {schema}.{table_name}."]

        full_table_name = f"[{schema}].[{table_name}]"
        update_column_names = [col for col in all_column_names if col not in pk_column_names]

        sql_insert = None
        if all_column_names:
            placeholders_insert = ", ".join(["?"] * len(all_column_names))
            cols_str_insert = ", ".join([f"[{col}]" for col in all_column_names])
            sql_insert = f"INSERT INTO {full_table_name} ({cols_str_insert}) VALUES ({placeholders_insert})"

        sql_update = None
        if update_column_names and pk_column_names:
            set_clause = ", ".join([f"[{col}] = ?" for col in update_column_names])
            where_clause_update = " AND ".join([f"[{pk_col}] = ?" for pk_col in pk_column_names])
            sql_update = f"UPDATE {full_table_name} SET {set_clause} WHERE {where_clause_update}"

        successfully_processed_rows_count = 0
        individual_row_errors = [] # Lista per errori di singole righe
        batch_level_errors = [] # Lista per errori a livello di batch (es. commit fallito)

        for i, row_data_tuple in enumerate(data_rows):
            row_data_dict = dict(zip(all_column_names, row_data_tuple))
            operation_successful_for_row = False

            # Tentativo di UPDATE
            if sql_update:
                update_values = [row_data_dict.get(col_name) for col_name in update_column_names]
                pk_values_for_where = [row_data_dict.get(pk_col_name) for pk_col_name in pk_column_names]

                if None in pk_values_for_where:
                    pass # PK con None, salto UPDATE, procede all'INSERT
                else:
                    try:
                        self.cursor.execute(sql_update, tuple(update_values + pk_values_for_where))
                        if self.cursor.rowcount > 0:
                            successfully_processed_rows_count += 1
                            operation_successful_for_row = True
                    except pyodbc.Error as e_upd:
                        err_msg = (f"Riga batch {i+1}/{len(data_rows)} (UPDATE): Errore DB su {full_table_name} "
                                   f"per PKs {pk_values_for_where}. Dati riga: {row_data_tuple}. Errore: {e_upd}")
                        print(f"DBIMPORTER ROW ERROR (UPDATE): {err_msg}")
                        individual_row_errors.append(err_msg)
                        # Continua con la prossima riga del batch
                    except Exception as e_gen_upd:
                        err_msg = (f"Riga batch {i+1}/{len(data_rows)} (UPDATE GENERIC): Errore su {full_table_name} "
                                   f"per PKs {pk_values_for_where}. Dati riga: {row_data_tuple}. Errore: {e_gen_upd}")
                        print(f"DBIMPORTER ROW ERROR (UPDATE GENERIC): {err_msg}")
                        individual_row_errors.append(err_msg)
                         # Continua con la prossima riga del batch
            
            if operation_successful_for_row:
                continue # Prossima riga

            # Tentativo di INSERT
            if sql_insert:
                try:
                    self.cursor.execute(sql_insert, row_data_tuple)
                    successfully_processed_rows_count += 1
                    operation_successful_for_row = True # Anche se l'update non c'era o non ha fatto nulla
                except pyodbc.Error as e_ins:
                    err_msg = (f"Riga batch {i+1}/{len(data_rows)} (INSERT): Errore DB su {full_table_name} "
                               f"per dati {row_data_tuple}. Errore: {e_ins}")
                    print(f"DBIMPORTER ROW ERROR (INSERT): {err_msg}")
                    individual_row_errors.append(err_msg)
                except Exception as e_gen_ins:
                    err_msg = (f"Riga batch {i+1}/{len(data_rows)} (INSERT GENERIC): Errore su {full_table_name} "
                               f"per dati {row_data_tuple}. Errore: {e_gen_ins}")
                    print(f"DBIMPORTER ROW ERROR (INSERT GENERIC): {err_msg}")
                    individual_row_errors.append(err_msg)
            elif not operation_successful_for_row : # Se l'update non è stato fatto e non c'è sql_insert
                err_msg = f"Riga batch {i+1}/{len(data_rows)}: Impossibile costruire query INSERT per {full_table_name} e UPDATE non applicabile/riuscito."
                print(err_msg)
                individual_row_errors.append(err_msg)

        # Gestione Commit/Rollback alla fine del processamento di tutte le righe del batch
        if successfully_processed_rows_count > 0:
            try:
                self.conn.commit()
                print(f"DBImporter: Commit eseguito per {successfully_processed_rows_count} righe (upsert) in {full_table_name}. "
                      f"{len(individual_row_errors)} righe in questo batch hanno avuto errori e sono state saltate.")
            except pyodbc.Error as e_commit:
                commit_error_msg = (f"Errore CRITICO durante il COMMIT per {full_table_name} dopo che {successfully_processed_rows_count} righe erano state processate con successo (apparentemente). "
                                    f"Errore Commit: {e_commit}. Tentativo di Rollback...")
                print(f"DBImporter: {commit_error_msg}")
                batch_level_errors.append(commit_error_msg)
                try:
                    self.conn.rollback()
                    print(f"DBImporter: Rollback eseguito per {full_table_name} a seguito di fallimento del COMMIT.")
                except pyodbc.Error as e_rb_after_commit_fail:
                    rb_err_msg = f"Errore aggiuntivo durante il ROLLBACK post-fallimento-commit per {full_table_name}: {e_rb_after_commit_fail}"
                    print(f"DBImporter: {rb_err_msg}")
                    batch_level_errors.append(rb_err_msg)
                successfully_processed_rows_count = 0 # Il commit è fallito, quindi nessuna riga è stata realmente commessa
        elif len(individual_row_errors) > 0 : # Nessuna riga processata con successo, ma ci sono stati errori di riga
            # Non c'è nulla da commettere. Potremmo voler fare rollback se c'era una transazione implicita iniziata,
            # ma dato autocommit=False, e nessuna operazione SQL riuscita, non dovrebbe essere strettamente necessario
            # a meno che qualche driver non si comporti in modo strano. Per sicurezza:
            try:
                self.conn.rollback() # Assicura che uno stato pulito sia mantenuto se errori hanno lasciato transazioni aperte.
                print(f"DBImporter: Rollback precauzionale per {full_table_name} dato che ci sono stati {len(individual_row_errors)} errori di riga e 0 successi.")
            except pyodbc.Error as e_rb_prec:
                 batch_level_errors.append(f"Errore durante il rollback precauzionale per {full_table_name}: {e_rb_prec}")
            print(f"DBImporter: Nessuna riga commessa per {full_table_name}. {len(individual_row_errors)} righe hanno fallito individualmente.")
        elif not data_rows:
             print(f"DBImporter: Nessun dato fornito nel batch per {full_table_name}. Nessuna operazione DB eseguita.")
        else: # Nessuna riga processata con successo e nessun errore di riga (es. tutte le righe filtrate prima del DB)
             print(f"DBImporter: Nessuna operazione DB eseguita o necessaria per {full_table_name} (batch di {len(data_rows)} righe).")

        # Gli errori restituiti al chiamante saranno una combinazione di errori di riga e di batch
        final_errors_to_report = individual_row_errors + batch_level_errors

        final_log_msg = (
            f"DEBUG DBIMPORTER: Fine upsert_data_batch per {full_table_name}. "
            f"Righe totali nel batch: {len(data_rows)}. "
            f"Righe effettivamente commesse: {successfully_processed_rows_count}. "
            f"Errori totali (riga + batch) rilevati: {len(final_errors_to_report)}. "
        )
        if final_errors_to_report:
            final_log_msg += f"Primi errori: [{'; '.join(final_errors_to_report[:2])}]"
        print(final_log_msg)
        return successfully_processed_rows_count, final_errors_to_report

    def upsert_doc_testa_batch(self, doc_testa_data: list[dict], schema='dbo') -> tuple[int, list[str], list[str]]:
        if not self.conn or not self.cursor:
            return 0, ["DB non connesso per DOC_TESTA."], []
        if not doc_testa_data:
            return 0, [], []

        table_name = "DOC_TESTA"
        full_table_name = f"[{schema}].[{table_name}]"

        # Define the order of columns as they are in the table or as preferred for INSERT
        # NUM_DOC, TIPO_DOC, DATA_DOC, CODICE_INTERLOCUTORE
        cols = ["NUM_DOC", "TIPO_DOC", "DATA_DOC", "CODICE_INTERLOCUTORE"]

        sql_check_exists = f"SELECT 1 FROM {full_table_name} WHERE NUM_DOC = ?"
        cols_str_insert = ", ".join([f"[{col}]" for col in cols])
        placeholders_insert = ", ".join(["?"] * len(cols))
        sql_insert = f"INSERT INTO {full_table_name} ({cols_str_insert}) VALUES ({placeholders_insert})"

        successfully_inserted_count = 0
        errors = []
        inserted_num_docs_list = [] # New list to store NUM_DOC of newly inserted headers

        for item_dict in doc_testa_data:
            num_doc = item_dict.get("NUM_DOC")
            if not num_doc:
                errors.append(f"Riga DOC_TESTA saltata: NUM_DOC mancante. Dati: {item_dict}")
                continue

            try:
                self.cursor.execute(sql_check_exists, num_doc)
                if self.cursor.fetchone():
                    # Record exists, skip insertion (as per "insert if not present")
                    print(f"DEBUG DBIMPORTER: Record DOC_TESTA con NUM_DOC='{num_doc}' già esistente. Inserimento saltato.")
                    continue

                # Prepare values in the correct order for SQL, converting dates to ISO strings
                row_values_list = []
                for col_name_iter in cols:
                    val = item_dict.get(col_name_iter)
                    if isinstance(val, datetime.date):
                        row_values_list.append(val.strftime('%Y-%m-%d'))
                    else:
                        row_values_list.append(val)

                self.cursor.execute(sql_insert, tuple(row_values_list))
                successfully_inserted_count += 1
                inserted_num_docs_list.append(num_doc) # Add successfully inserted NUM_DOC
            except pyodbc.Error as e_sql:
                err_msg = f"Errore DB (DOC_TESTA) per NUM_DOC '{num_doc}': {e_sql}. Dati: {item_dict}"
                print(f"DBIMPORTER ERROR: {err_msg}")
                errors.append(err_msg)
            except Exception as e_gen:
                err_msg = f"Errore generico (DOC_TESTA) per NUM_DOC '{num_doc}': {e_gen}. Dati: {item_dict}"
                print(f"DBIMPORTER ERROR: {err_msg}")
                errors.append(err_msg)

        if successfully_inserted_count > 0:
            try:
                self.conn.commit()
                print(f"DBImporter: Commit eseguito per {successfully_inserted_count} righe inserite in {full_table_name}.")
            except pyodbc.Error as e_commit:
                errors.append(f"Errore CRITICO COMMIT (DOC_TESTA): {e_commit}. Tentativo di Rollback...")
                try:
                    self.conn.rollback()
                except pyodbc.Error as e_rb:
                    errors.append(f"Errore CRITICO ROLLBACK (DOC_TESTA): {e_rb}")
                successfully_inserted_count = 0 # None were actually committed
        elif errors and not successfully_inserted_count: # No successes but errors occurred
             try: self.conn.rollback() # Rollback any potential uncommitted changes from failed attempts
             except pyodbc.Error as e_rb_err: errors.append(f"Errore ROLLBACK precauzionale (DOC_TESTA): {e_rb_err}")

        return successfully_inserted_count, errors, inserted_num_docs_list

    def insert_doc_righe_batch(self, doc_righe_data: list[dict], schema='dbo') -> tuple[int, list[str]]:
        if not self.conn or not self.cursor:
            return 0, ["DB non connesso per DOC_RIGHE."]
        if not doc_righe_data:
            return 0, []

        table_name = "DOC_RIGHE"
        full_table_name = f"[{schema}].[{table_name}]"

        # Define column order for INSERT - ID_RIGA is identity and should be excluded
        cols = [
            "NUM_DOC", "COD_ART", "DES", "QTA", "TIPO_MIS", "PREZZO",
            "SCONTO1", "SCONTO2", "SCONTO3", "PREZZO_NETTO", "OMAGGIO_SN",
            "COD_IVA", "ALIQUOTA_IVA", "PREZZO_VEND_CONS", "COD_REP", "REPARTO",
            "EAN1", "EAN2", "EAN3", "EAN4", "EAN5", "EAN6", "EAN7", "EAN8", "EAN9", "EAN10",
            "RIF_ORDINE"
        ]

        cols_str_insert = ", ".join([f"[{col}]" for col in cols])
        placeholders_insert = ", ".join(["?"] * len(cols))
        sql_insert = f"INSERT INTO {full_table_name} ({cols_str_insert}) VALUES ({placeholders_insert})"

        rows_to_insert = []
        for item_dict in doc_righe_data:
            # Ensure all columns are present in the tuple, defaulting to None if missing in dict
            row_tuple = tuple(item_dict.get(col_name) for col_name in cols)
            rows_to_insert.append(row_tuple)

        # Convert Decimal to string to avoid pyodbc locale issues
        processed_rows = [
            tuple(str(item) if isinstance(item, Decimal) else item for item in row)
            for row in rows_to_insert
        ]
        rows_to_insert = processed_rows

        successfully_inserted_count = 0
        errors = []

        if not rows_to_insert:
            return 0, []

        try:
            # Using executemany for batch insert
            self.cursor.fast_executemany = True # Enable for pyodbc if available and beneficial
            self.cursor.executemany(sql_insert, rows_to_insert)
            # cursor.rowcount for executemany might be -1 or the number of rows with some drivers.
            # We'll assume success if no exception, and count based on input rows for this example.
            # For a more accurate count, one might need to loop or use specific driver features.
            # However, if an error occurs, it usually stops the whole batch.
            successfully_inserted_count = len(rows_to_insert)
            self.conn.commit()
            print(f"DBImporter: Commit eseguito per {successfully_inserted_count} righe inserite in {full_table_name} (tramite executemany).")
        except pyodbc.Error as e_sql:
            errors.append(f"Errore DB batch (DOC_RIGHE): {e_sql}. Numero righe nel batch: {len(rows_to_insert)}")
            try: self.conn.rollback()
            except pyodbc.Error as e_rb: errors.append(f"Errore ROLLBACK (DOC_RIGHE): {e_rb}")
            successfully_inserted_count = 0
        except Exception as e_gen:
            errors.append(f"Errore generico batch (DOC_RIGHE): {e_gen}. Numero righe nel batch: {len(rows_to_insert)}")
            try: self.conn.rollback()
            except pyodbc.Error as e_rb_gen: errors.append(f"Errore ROLLBACK generico (DOC_RIGHE): {e_rb_gen}")
            successfully_inserted_count = 0

        return successfully_inserted_count, errors

    def insert_lisprelievo_batch(self, lisprelievo_data: list[dict], schema='dbo') -> tuple[int, list[str]]:
        if not self.conn or not self.cursor:
            return 0, ["DB non connesso per LISPRELIEVO."]
        if not lisprelievo_data:
            return 0, []

        table_name = "LISPRELIEVO"
        full_table_name = f"[{schema}].[{table_name}]"

        # Define column order for INSERT - ID_ORDINE is identity and should be excluded
        cols = [
            "MAGAZZ", "CLI", "DATA_ORD", "N_LISTA", "DATA_LIST",
            "COD_ART", "DES", "EAN", "COLL_RICH", "COLL_EVASI",
            "COLL_INEVASI", "MPL", "STATO", "RIFORD"
        ]

        cols_str_insert = ", ".join([f"[{col}]" for col in cols])
        placeholders_insert = ", ".join(["?"] * len(cols))
        sql_insert = f"INSERT INTO {full_table_name} ({cols_str_insert}) VALUES ({placeholders_insert})"

        rows_to_insert = []
        for item_dict in lisprelievo_data:
            # Prepare tuple, converting dates to ISO strings for compatibility
            row_values_list = []
            for col_name in cols:
                val = item_dict.get(col_name)
                if isinstance(val, datetime.date): # Handle dates specifically
                    row_values_list.append(val.strftime('%Y-%m-%d'))
                else:
                    row_values_list.append(val)
            rows_to_insert.append(tuple(row_values_list))

        successfully_inserted_count = 0
        errors_list = [] # Changed variable name from errors to errors_list to avoid conflict

        if not rows_to_insert:
            return 0, []

        try:
            self.cursor.fast_executemany = True
            self.cursor.executemany(sql_insert, rows_to_insert)
            # For many drivers, rowcount after executemany is -1 or number of batches.
            # Assuming success if no error, and all rows in batch were processed.
            successfully_inserted_count = len(rows_to_insert)
            self.conn.commit()
            print(f"DBImporter: Commit eseguito per {successfully_inserted_count} righe inserite in {full_table_name} (LISPRELIEVO).")
        except pyodbc.Error as e_sql:
            errors_list.append(f"Errore DB batch (LISPRELIEVO): {e_sql}. Numero righe nel batch: {len(rows_to_insert)}")
            try: self.conn.rollback()
            except pyodbc.Error as e_rb: errors_list.append(f"Errore ROLLBACK (LISPRELIEVO): {e_rb}")
            successfully_inserted_count = 0
        except Exception as e_gen:
            errors_list.append(f"Errore generico batch (LISPRELIEVO): {e_gen}. Numero righe nel batch: {len(rows_to_insert)}")
            try: self.conn.rollback()
            except pyodbc.Error as e_rb_gen: errors_list.append(f"Errore ROLLBACK generico (LISPRELIEVO): {e_rb_gen}")
            successfully_inserted_count = 0

        return successfully_inserted_count, errors_list

    def check_n_lista_exists(self, n_lista: str, schema='dbo') -> tuple[bool | None, str | None]:
        """
        Checks if a given N_LISTA already exists in the LISPRELIEVO table.
        Returns (True/False/None, error_message_or_None).
        True if exists, False if not, None if error during check.
        """
        if not self.conn or not self.cursor:
            return None, "DB non connesso per check N_LISTA."

        table_name = "LISPRELIEVO"
        full_table_name = f"[{schema}].[{table_name}]"

        # Assuming N_LISTA in the database is a string type that matches the input.
        # If it's numeric in DB, the placeholder might not need quotes, but pyodbc handles types.
        sql_check = f"SELECT 1 FROM {full_table_name} WHERE N_LISTA = ?"

        try:
            self.cursor.execute(sql_check, n_lista)
            return self.cursor.fetchone() is not None, None
        except pyodbc.Error as e_sql:
            err_msg = f"Errore DB durante check N_LISTA '{n_lista}' in {full_table_name}: {e_sql}"
            print(f"DBIMPORTER ERROR: {err_msg}")
            return None, err_msg
        except Exception as e_gen:
            err_msg = f"Errore generico durante check N_LISTA '{n_lista}' in {full_table_name}: {e_gen}"
            print(f"DBIMPORTER ERROR: {err_msg}")
            return None, err_msg

    # def populate_prodotti_for(self, schema='dbo'):
    #     if not self.conn or not self.cursor:
    #         print("DBImporter (PRODOTTI_FOR): DB non connesso.")
    #         return 0, ["DB non connesso."]

    #     print(f"DBImporter (PRODOTTI_FOR): Inizio popolamento tabella {schema}.PRODOTTI_FOR.")

    #     anarti_data = []
    #     # Colonne da ANARTI necessarie per PRODOTTI_FOR o per logica interna
    #     anarti_cols_to_select = [
    #         "COD_ART", "COD_EAN_ULT_INS", "DES", "UN_MIS", "TIPO_UN_MIS", "ULT_COD_FORNI",
    #         "P_IVA_FORNI", # Assicurarsi che P_IVA_FORNI da ANARTI sia selezionato
    #         "COD_ART_FORNI_1", "COD_ART_FORNI_2", "COD_ART_FORNI_3", "AREA", "SETTORE",
    #         "COMPARTO", "FAM", "SUB_FAM", "AL_IVA", "STATO_ART", "IMB", "PZ_X_CART",
    #         "CART_X_PALLET", "GEST_POS", "LEGAME", "FASC_APP", "REP_CASSA", "PLU", "ASSORT_SN"
    #     ]
    #     try:
    #         anarti_table_name = f"[{schema}].[ANARTI]"
    #         # Costruisci la stringa SELECT in modo sicuro
    #         select_cols_str = ", ".join([f"[{col}]" for col in anarti_cols_to_select])
    #         query_anarti = f"SELECT {select_cols_str} FROM {anarti_table_name}"
    #         self.cursor.execute(query_anarti)
    #         rows = self.cursor.fetchall()
    #         for row in rows:
    #             anarti_data.append(dict(zip(anarti_cols_to_select, row)))
    #         print(f"DBImporter (PRODOTTI_FOR): Reperiti {len(anarti_data)} record da ANARTI.")
    #     except pyodbc.Error as e:
    #         err_msg = f"DBImporter (PRODOTTI_FOR): Errore nel reperire dati da ANARTI: {e}"
    #         print(err_msg)
    #         self.conn.rollback() # Rollback in caso di errore di lettura
    #         return 0, [err_msg]

    #     anafor_data_map = {}
    #     anafor_cols_to_select = [ # P_IVA_FORNI rimosso da qui
    #         "COD_FORNI", "RAGSOC", "INDIRIZZO", "LOCALITA", "PROV", "CAP", "TEL", "FAX", "EMAIL"
    #     ]
    #     try:
    #         anafor_table_name = f"[{schema}].[ANAFOR]"
    #         select_cols_str_anafor = ", ".join([f"[{col}]" for col in anafor_cols_to_select])
    #         query_anafor = f"SELECT {select_cols_str_anafor} FROM {anafor_table_name}"
    #         self.cursor.execute(query_anafor)
    #         rows = self.cursor.fetchall()
    #         for row in rows:
    #             # Chiave della mappa: COD_FORNI da ANAFOR (che dovrebbe essere stringa, come da XML)
    #             anafor_data_map[str(row.COD_FORNI).strip()] = dict(zip(anafor_cols_to_select, row))
    #         print(f"DBImporter (PRODOTTI_FOR): Reperiti {len(anafor_data_map)} record da ANAFOR e mappati.")
    #     except pyodbc.Error as e:
    #         err_msg = f"DBImporter (PRODOTTI_FOR): Errore nel reperire dati da ANAFOR: {e}"
    #         print(err_msg)
    #         self.conn.rollback() # Rollback in caso di errore di lettura
    #         return 0, [err_msg]

    #     prodotti_for_data_to_upsert = []
    #     prodotti_for_target_cols = [
    #         "COD_ART", "COD_EAN_ULT_INS", "DES", "UN_MIS", "TIPO_UN_MIS", "COD_FORNI",
    #         "P_IVA_FORNI", "RAGSOC", "INDIRIZZO", "LOCALITA", "PROV", "CAP", "TEL", "FAX", "EMAIL",
    #         "COD_ART_FORNI_1", "COD_ART_FORNI_2", "COD_ART_FORNI_3", "AREA", "SETTORE", "COMPARTO",
    #         "FAM", "SUB_FAM", "AL_IVA", "STATO_ART", "IMB", "PZ_X_CART", "CART_X_PALLET",
    #         "GEST_POS", "LEGAME", "DATA_AGG", "FASC_APP", "REP_CASSA", "PLU", "ASSORT_SN"
    #     ]
    #     prodotti_for_pk_cols = ["COD_ART", "COD_FORNI"]
    #     current_datetime = datetime.datetime.now()

    #     for anarti_record in anarti_data:
    #         ult_cod_forni_str = anarti_record.get("ULT_COD_FORNI")
    #         if ult_cod_forni_str is None:
    #             continue

    #         ult_cod_forni_str = str(ult_cod_forni_str).strip() # Chiave per lookup in anafor_data_map

    #         anafor_record = anafor_data_map.get(ult_cod_forni_str)

    #         if anafor_record:
    #             pf_record_dict = {}
    #             try:
    #                 # Da ANARTI
    #                 cod_art_val = anarti_record.get("COD_ART")
    #                 if isinstance(cod_art_val, str) and cod_art_val.isdigit():
    #                     pf_record_dict["COD_ART"] = int(cod_art_val)
    #                 elif isinstance(cod_art_val, (int, float)): # float per robustezza se Decimal viene da DB
    #                     pf_record_dict["COD_ART"] = int(cod_art_val)
    #                 else:
    #                     raise ValueError(f"COD_ART '{cod_art_val}' non convertibile a intero.")

    #                 pf_record_dict["COD_EAN_ULT_INS"] = anarti_record.get("COD_EAN_ULT_INS")
    #                 pf_record_dict["DES"] = anarti_record.get("DES")
    #                 pf_record_dict["UN_MIS"] = anarti_record.get("UN_MIS")
    #                 pf_record_dict["TIPO_UN_MIS"] = anarti_record.get("TIPO_UN_MIS")

    #                 # COD_FORNI per PRODOTTI_FOR è ULT_COD_FORNI da ANARTI, convertito a INT
    #                 if ult_cod_forni_str.isdigit():
    #                     pf_record_dict["COD_FORNI"] = int(ult_cod_forni_str)
    #                 else:
    #                     raise ValueError(f"ULT_COD_FORNI '{ult_cod_forni_str}' non convertibile a intero.")

    #                 pf_record_dict["COD_ART_FORNI_1"] = anarti_record.get("COD_ART_FORNI_1")
    #                 pf_record_dict["COD_ART_FORNI_2"] = anarti_record.get("COD_ART_FORNI_2")
    #                 pf_record_dict["COD_ART_FORNI_3"] = anarti_record.get("COD_ART_FORNI_3")
    #                 pf_record_dict["AREA"] = anarti_record.get("AREA")
    #                 pf_record_dict["SETTORE"] = anarti_record.get("SETTORE")
    #                 pf_record_dict["COMPARTO"] = anarti_record.get("COMPARTO")
    #                 pf_record_dict["FAM"] = anarti_record.get("FAM")
    #                 pf_record_dict["SUB_FAM"] = anarti_record.get("SUB_FAM")
    #                 pf_record_dict["AL_IVA"] = anarti_record.get("AL_IVA")
    #                 pf_record_dict["STATO_ART"] = anarti_record.get("STATO_ART")
    #                 pf_record_dict["IMB"] = anarti_record.get("IMB")
    #                 pf_record_dict["PZ_X_CART"] = anarti_record.get("PZ_X_CART")

    #                 cart_x_pallet_val = anarti_record.get("CART_X_PALLET")
    #                 if isinstance(cart_x_pallet_val, str) and cart_x_pallet_val.isdigit():
    #                     pf_record_dict["CART_X_PALLET"] = int(cart_x_pallet_val)
    #                 elif isinstance(cart_x_pallet_val, (int, float)):
    #                     pf_record_dict["CART_X_PALLET"] = int(cart_x_pallet_val)
    #                 else:
    #                     pf_record_dict["CART_X_PALLET"] = None # O gestisci come errore se richiesto

    #                 pf_record_dict["GEST_POS"] = anarti_record.get("GEST_POS")
    #                 pf_record_dict["LEGAME"] = anarti_record.get("LEGAME")
    #                 pf_record_dict["FASC_APP"] = anarti_record.get("FASC_APP")
    #                 pf_record_dict["REP_CASSA"] = anarti_record.get("REP_CASSA")
    #                 pf_record_dict["PLU"] = anarti_record.get("PLU")
    #                 pf_record_dict["ASSORT_SN"] = anarti_record.get("ASSORT_SN")

    #                 # P_IVA_FORNI da ANARTI
    #                 pf_record_dict["P_IVA_FORNI"] = anarti_record.get("P_IVA_FORNI")

    #                 # Da ANAFOR (senza P_IVA_FORNI)
    #                 pf_record_dict["RAGSOC"] = anafor_record.get("RAGSOC")
    #                 pf_record_dict["INDIRIZZO"] = anafor_record.get("INDIRIZZO")
    #                 pf_record_dict["LOCALITA"] = anafor_record.get("LOCALITA")
    #                 pf_record_dict["PROV"] = anafor_record.get("PROV")
    #                 pf_record_dict["CAP"] = anafor_record.get("CAP")
    #                 pf_record_dict["TEL"] = anafor_record.get("TEL")
    #                 pf_record_dict["FAX"] = anafor_record.get("FAX")
    #                 pf_record_dict["EMAIL"] = anafor_record.get("EMAIL")

    #                 pf_record_dict["DATA_AGG"] = current_datetime

    #                 row_tuple = tuple(pf_record_dict.get(col_name) for col_name in prodotti_for_target_cols)
    #                 prodotti_for_data_to_upsert.append(row_tuple)

    #             except ValueError as ve:
    #                 print(f"DBImporter (PRODOTTI_FOR): Riga ANARTI saltata per COD_ART '{anarti_record.get('COD_ART')}' / ULT_COD_FORNI '{ult_cod_forni_str}' a causa di errore di conversione: {ve}")
    #                 continue

    #     if not prodotti_for_data_to_upsert:
    #         msg = "DBImporter (PRODOTTI_FOR): Nessun dato valido da inserire/aggiornare in PRODOTTI_FOR dopo il join e la validazione."
    #         print(msg)
    #         # Non è un errore fatale, potrebbe non esserci nulla da aggiornare. Commit/Rollback gestito da upsert.
    #         return 0, []

    #     print(f"DBImporter (PRODOTTI_FOR): Tentativo di UPSERT di {len(prodotti_for_data_to_upsert)} record in PRODOTTI_FOR.")

    #     processed_count, errors = self.upsert_data_batch(
    #         table_name="PRODOTTI_FOR",
    #         data_rows=prodotti_for_data_to_upsert,
    #         all_column_names=prodotti_for_target_cols,
    #         pk_column_names=prodotti_for_pk_cols,
    #         schema=schema
    #     )

    #     if errors:
    #         # Non fare rollback qui, upsert_data_batch gestisce il suo commit/rollback per batch.
    #         # Gli errori sono già stati loggati da upsert_data_batch.
    #         print(f"DBImporter (PRODOTTI_FOR): Errori durante UPSERT in PRODOTTI_FOR (dettagli già loggati da upsert_data_batch): {len(errors)} errori totali.")

    #     # Se processed_count > 0 e non ci sono stati errori a livello di batch da upsert_data_batch,
    #     # la transazione per quei dati è stata commessa da upsert_data_batch.
    #     # Se le query iniziali per ANARTI/ANAFOR erano parte di una transazione più ampia
    #     # che deve essere commessa solo se TUTTO va bene, allora il commit dovrebbe essere gestito più in alto.
    #     # Attualmente, ogni chiamata a upsert_data_batch gestisce il proprio commit/rollback.
    #     # Le letture iniziali da ANARTI/ANAFOR non modificano dati, quindi il rollback fatto in caso di errore di lettura è ok.

    #     print(f"DBImporter (PRODOTTI_FOR): Popolamento completato. Righe processate (tentativi di upsert): {processed_count}. Errori riportati: {len(errors)}.")
    #     return processed_count, errors

    def get_anafor_by_cod_forni_list(self, cod_forni_list: list[str], schema='dbo') -> dict:
        """
        Retrieves ANAFOR records from the database for a given list of COD_FORNI.
        Returns a dictionary mapping COD_FORNI (string) to ANAFOR record dictionaries.
        """
        if not self.conn or not self.cursor:
            print("DBImporter (get_anafor): DB non connesso.")
            return {}
        if not cod_forni_list:
            return {}

        anafor_records_map = {}
        # Define columns to select from ANAFOR, matching what's needed for PRODOTTI_FOR
        # and what was previously read by file_processor for current_file_anafor_map
        anafor_cols_to_select = [
            "COD_FORNI", "RAGSOC", "INDIRIZZO", "LOCALITA", "PROV", "CAP", "TEL", "FAX", "EMAIL"
            # P_IVA_FORNI is intentionally NOT selected from ANAFOR here as per latest requirement
        ]

        # Ensure COD_FORNI in the DB is treated as string for the IN clause, or adjust if it's numeric
        # The XML defines ANAFOR.COD_FORNI as string.
        placeholders = ", ".join(["?" for _ in cod_forni_list])
        cols_str = ", ".join([f"[{col}]" for col in anafor_cols_to_select])

        # It's important that the type of COD_FORNI in the DB matches the type of values in cod_forni_list
        # If COD_FORNI in DB is INT, values in cod_forni_list might need conversion if they are strings.
        # Assuming COD_FORNI in ANAFOR table is VARCHAR or similar text type, as per XML definition.
        query = f"SELECT {cols_str} FROM [{schema}].[ANAFOR] WHERE [COD_FORNI] IN ({placeholders})"

        try:
            self.cursor.execute(query, tuple(cod_forni_list))
            rows = self.cursor.fetchall()
            for row in rows:
                row_dict = dict(zip(anafor_cols_to_select, row))
                # Key by string version of COD_FORNI for consistent lookup
                anafor_records_map[str(row_dict["COD_FORNI"]).strip()] = row_dict
            print(f"DBImporter (get_anafor): Reperiti {len(anafor_records_map)} record da ANAFOR per {len(cod_forni_list)} codici richiesti.")
        except pyodbc.Error as e:
            print(f"DBImporter (get_anafor): Errore nel reperire dati da ANAFOR: {e}")
            # Do not rollback here as this is a read operation within a potentially larger transaction
            return {} # Return empty if error
        except Exception as e_gen:
            print(f"DBImporter (get_anafor): Errore generico: {e_gen}")
            return {}

        return anafor_records_map

    def insert_varlis_batch(self, data_rows: list[tuple], all_column_names: list[str], schema='dbo') -> tuple[int, list[str]]:
        table_name = "VARLIS"
        # Attempt to get main_gui global, but handle if not available (e.g. running importer standalone)
        # This is not ideal, direct GUI access from DBImporter is problematic.
        # Consider callbacks or returning more structured error/info messages.
        _main_gui_ref = None
        try:
            # This is a hacky way to check if main_gui is defined in the global scope of the caller (itscomm_main)
            # A better solution would be to pass a logger/callback object.
            if 'main_gui' in globals() and globals()['main_gui'] is not None:
                 _main_gui_ref = globals()['main_gui']
        except NameError:
            pass # main_gui not defined in this scope or globals() of caller

        full_table_name = f"[{schema}].[{table_name}]"

        if not self.conn or not self.cursor:
            if _main_gui_ref: _main_gui_ref.safe_insert_listbox(f"DBImporter ({table_name}): DB non connesso.", is_error=True)
            print(f"DBImporter ({table_name}): DB non connesso.")
            return 0, [f"DB non connesso per {table_name}."]
        if not data_rows:
            if _main_gui_ref: _main_gui_ref.safe_insert_listbox(f"DBImporter ({table_name}): Nessun dato fornito.")
            print(f"DBImporter ({table_name}): Nessun dato fornito.")
            return 0, []

        # Convert Decimal to string to avoid pyodbc locale issues
        processed_rows = [
            tuple(str(item) if isinstance(item, Decimal) else item for item in row)
            for row in data_rows
        ]
        data_rows = processed_rows

        # Columns for INSERT statement (ID_VAR is identity, should not be in INSERT list)
        # The all_column_names list passed from itscomm_main should already be correct.
        cols_for_sql_insert = [col for col in all_column_names if col.upper() != "ID_VAR"]

        if not cols_for_sql_insert:
            err_no_cols = f"Nessuna colonna valida per INSERT in {table_name} dopo aver escluso ID_VAR."
            if _main_gui_ref: _main_gui_ref.safe_insert_listbox(err_no_cols, is_error=True)
            print(f"DBImporter ({table_name}): {err_no_cols}")
            return 0, [err_no_cols]

        cols_str_insert = ", ".join([f"[{col}]" for col in cols_for_sql_insert])
        placeholders_insert = ", ".join(["?"] * len(cols_for_sql_insert))
        sql_insert = f"INSERT INTO {full_table_name} ({cols_str_insert}) VALUES ({placeholders_insert})"

        if _main_gui_ref: _main_gui_ref.safe_insert_listbox(f"DBImporter ({table_name}): SQL Insert: {sql_insert[:200]}...") # Log truncated SQL
        print(f"DBImporter ({table_name}): SQL Insert: {sql_insert[:200]}...")


        successfully_inserted_count = 0
        errors = []

        try:
            self.cursor.fast_executemany = True
            self.cursor.executemany(sql_insert, data_rows)

            # cursor.rowcount for executemany is driver-dependent.
            # -1 if no info, or number of rows. For successful full batch, assume len(data_rows).
            if self.cursor.rowcount == -1 or self.cursor.rowcount == len(data_rows):
                 successfully_inserted_count = len(data_rows)
            elif self.cursor.rowcount >= 0: # Some drivers might return actual rows
                 successfully_inserted_count = self.cursor.rowcount
            else: # Should not happen, but as a fallback assume all were attempted if no error.
                 successfully_inserted_count = len(data_rows)


            self.conn.commit()
            msg_commit = f"DBImporter: Commit eseguito per {successfully_inserted_count} righe inserite in {full_table_name}."
            if _main_gui_ref: _main_gui_ref.safe_insert_listbox(msg_commit)
            print(msg_commit)
        except pyodbc.Error as e_sql:
            err_sql_msg = f"Errore DB batch (INSERT {table_name}): {e_sql}. Dati campione (prima riga): {data_rows[0] if data_rows else 'N/A'}"
            errors.append(err_sql_msg)
            if _main_gui_ref: _main_gui_ref.safe_insert_listbox(err_sql_msg, is_error=True)
            print(f"DBImporter ({table_name}): {err_sql_msg}")
            try:
                self.conn.rollback()
                msg_rb = f"DBImporter: Rollback eseguito per {table_name} a causa di errore."
                if _main_gui_ref: _main_gui_ref.safe_insert_listbox(msg_rb, is_error=True)
                print(msg_rb)
            except pyodbc.Error as e_rb:
                rb_err = f"Errore CRITICO durante ROLLBACK per {table_name}: {e_rb}"
                errors.append(rb_err)
                if _main_gui_ref: _main_gui_ref.safe_insert_listbox(rb_err, is_error=True)
                print(rb_err)
            successfully_inserted_count = 0
        except Exception as e_gen:
            err_gen_msg = f"Errore generico batch (INSERT {table_name}): {e_gen}. Dati campione: {data_rows[0] if data_rows else 'N/A'}"
            errors.append(err_gen_msg)
            if _main_gui_ref: _main_gui_ref.safe_insert_listbox(err_gen_msg, is_error=True)
            print(f"DBImporter ({table_name}): {err_gen_msg}")
            try:
                self.conn.rollback()
                msg_rb_gen = f"DBImporter: Rollback generico eseguito per {table_name}."
                if _main_gui_ref: _main_gui_ref.safe_insert_listbox(msg_rb_gen, is_error=True)
                print(msg_rb_gen)
            except pyodbc.Error as e_rb_gen:
                rb_gen_err = f"Errore CRITICO generico durante ROLLBACK per {table_name}: {e_rb_gen}"
                errors.append(rb_gen_err)
                if _main_gui_ref: _main_gui_ref.safe_insert_listbox(rb_gen_err, is_error=True)
                print(rb_gen_err)
            successfully_inserted_count = 0

        return successfully_inserted_count, errors

if __name__ == '__main__':
    # COMPILARE CON I PROPRI DETTAGLI DI TEST
    test_driver = "{SQL Server}"
    test_server = "localhost\\SQLEXPRESS"
    test_db_name = "ITS_ORDINE"
    test_user = "sa"
    test_password = "your_password_here" # CAMBIARE!

    test_schema = "dbo"
    from decimal import Decimal

    importer = DBImporter(test_driver, test_server, test_db_name, test_user, test_password)

    print(f"Tentativo di connessione a {test_server} DB {test_db_name}...")
    conn_success, conn_msg = importer.connect()
    if conn_success:
        print("Connessione DB riuscita.")

        # Test ANAFOR
        anafor_table = "ANAFOR"
        anafor_cols = ["COD_FORNI", "RAGSOC", "INDIRIZZO", "LOCALITA", "PROV", "CAP", "TEL", "FAX", "EMAIL"]
        anafor_pk_cols = ["COD_FORNI"]
        anafor_data = [
            ('00001', 'Fornitore Test 1 UPDATED', 'Via Prova Aggiornata 100', 'CITTA TEST UPD', 'TU', '00101', '11111', None, 'test1upd@example.com'), # Update
            ('99999', 'Nuovo Fornitore 99999', 'Via Nuova 1', 'NUOVA CITTA', 'NC', '00200', '09876', None, 'test9@example.com')    # Insert
        ]
        print(f"\n--- Test {anafor_table} (UPSERT) ---")
        try:
            importer.cursor.execute(f"DELETE FROM [{test_schema}].[{anafor_table}] WHERE COD_FORNI = '00001' OR COD_FORNI = '99999'")
            importer.cursor.execute(f"INSERT INTO [{test_schema}].[{anafor_table}] (COD_FORNI, RAGSOC) VALUES ('00001', 'Vecchio Fornitore 00001')")
            importer.conn.commit()
            print(f"Dati di setup per {anafor_table} inseriti/puliti.")
        except Exception as e_setup:
            print(f"Errore setup dati {anafor_table}: {e_setup}")
            importer.conn.rollback()

        p_count, p_errs = importer.upsert_data_batch(anafor_table, anafor_data, anafor_cols, anafor_pk_cols, test_schema)
        print(f"{anafor_table} Upsert: Processate={p_count}, Errori={p_errs if p_errs else 'Nessuno'}")

        # Test ANARTI
        anarti_table = "ANARTI"
        anarti_cols_all = ["COD_ART", "COD_EAN_ULT_INS", "DES", "DES_SCONTR", "GRAM_LORD", "GRAM_NETT", "UN_MIS", "TIPO_UN_MIS", "COD_FORNI", "P_IVA_FORNI", "COD_ART_FORNI_1", "COD_ART_FORNI_2", "COD_ART_FORNI_3", "AREA", "SETTORE", "COMPARTO", "FAM", "SUB_FAM", "AL_IVA", "STATO_ART", "IMB", "PZ_X_CART", "CART_X_PALLET", "DURAB_PV", "DURAB_TOT", "GEST_POS", "Legame_Master_Mix_Match", "DATA_INS", "DATA_VAR", "Fascia_Appartenenza", "REP_CASSA", "PLU", "ASSORT_SN"]
        anarti_pk_cols = ["COD_ART"]
        anarti_data = [
            ('ART001', '111', 'Articolo 1 UPD', 'Art1U', Decimal('1.0'), Decimal('1.0'), 'PZ','P','00001',None,None,None,None,'A','S','C','F','SF','22','S','I','1','1','1','1','S',None,'250101','250101','FA','RC','PLU1','S'), # Update
            ('ART002', '222', 'Articolo 2 NEW', 'Art2N', Decimal('2.0'), Decimal('2.0'), 'PZ','P','99999',None,None,None,None,'A','S','C','F','SF','22','S','I','1','1','1','1','S',None,'250101','250101','FA','RC','PLU2','S'), # Insert (COD_FORNI 99999 deve esistere)
            ('ART003', '333', 'Articolo 3 FK_ERR', 'Art3F', Decimal('3.0'), Decimal('3.0'), 'PZ','P','NOEXST',None,None,None,None,'A','S','C','F','SF','22','S','I','1','1','1','1','S',None,'250101','250101','FA','RC','PLU3','N')  # FK error
        ]
        print(f"\n--- Test {anarti_table} (UPSERT) ---")
        try:
            importer.cursor.execute(f"DELETE FROM [{test_schema}].[{anarti_table}] WHERE COD_ART LIKE 'ART%';")
            importer.cursor.execute(f"INSERT INTO [{test_schema}].[{anarti_table}] (COD_ART, DES, COD_FORNI) VALUES ('ART001', 'Articolo 1 OLD', '00001')")
            importer.conn.commit()
            print(f"Dati di setup per {anarti_table} inseriti/puliti.")
        except Exception as e_setup:
            print(f"Errore setup dati {anarti_table}: {e_setup}")
            importer.conn.rollback()

        p_count, p_errs = importer.upsert_data_batch(anarti_table, anarti_data, anarti_cols_all, anarti_pk_cols, test_schema)
        print(f"{anarti_table} Upsert: Processate={p_count}, Errori={p_errs if p_errs else 'Nessuno'}")

        importer.disconnect()
        print("\nDisconnesso dal DB.")
    else:
        print(f"Connessione DB fallita: {conn_msg}")
