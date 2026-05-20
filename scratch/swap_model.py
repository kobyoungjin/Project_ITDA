import shutil
from pathlib import Path

DATA_DIR = Path("api/data/ksl_training")
MAIN_MODEL = DATA_DIR / "knn_model.pkl"
MAIN_CSV = DATA_DIR / "ksl_dataset.csv"

DIALOGUE_MODEL = DATA_DIR / "knn_model_dialogue.pkl"
DIALOGUE_CSV = DATA_DIR / "ksl_dataset_dialogue.csv"

BACKUP_MODEL = DATA_DIR / "knn_model_backup.pkl"
BACKUP_CSV = DATA_DIR / "ksl_dataset_backup.csv"

def swap_to_dialogue():
    print("[ITDA Model Swapper] Swapping to Dialogue Model...")
    
    if not DIALOGUE_MODEL.exists():
        print(f"Error: Dialogue model ({DIALOGUE_MODEL}) not found. Please train it first.")
        return
        
    # Backup current main model
    if MAIN_MODEL.exists():
        shutil.copy(MAIN_MODEL, BACKUP_MODEL)
        print("Backed up current main model to knn_model_backup.pkl")
    if MAIN_CSV.exists():
        shutil.copy(MAIN_CSV, BACKUP_CSV)
        print("Backed up current main CSV to ksl_dataset_backup.csv")
        
    # Copy dialogue model to main
    shutil.copy(DIALOGUE_MODEL, MAIN_MODEL)
    shutil.copy(DIALOGUE_CSV, MAIN_CSV)
    print("Successfully swapped main model to the Dialogue Model!")
    print("Please restart the FastAPI server (or reload) to apply changes.")

def restore_main():
    print("[ITDA Model Swapper] Restoring Main Model from backup...")
    
    if not BACKUP_MODEL.exists():
        print(f"Error: Backup model ({BACKUP_MODEL}) not found.")
        return
        
    # Copy backup to main
    shutil.copy(BACKUP_MODEL, MAIN_MODEL)
    if BACKUP_CSV.exists():
        shutil.copy(BACKUP_CSV, MAIN_CSV)
    print("Successfully restored the Main Model from backup!")
    print("Please restart the FastAPI server (or reload) to apply changes.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "restore":
        restore_main()
    else:
        swap_to_dialogue()
