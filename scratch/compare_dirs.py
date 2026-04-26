import filecmp
import os

dir1 = r"C:\Users\Peto\Desktop\PICA\FUTURE_CLEAN_24\Nexus-Future-clean-main"
dir2 = r"C:\Users\Peto\Desktop\PICA\FUTURE_CLEAN_24\Nexus-Pokrok"
ignore = ['.venv', 'venv', '__pycache__', '.git', '.idea', 'node_modules', 'logs', 'scratch', 'db_data', 'alembic', '.pytest_cache']

dcmp = filecmp.dircmp(dir1, dir2, ignore=ignore)

output = []

def get_diff(dcmp, path=""):
    if dcmp.left_only:
        output.append(f"Len v Nexus-Future-clean-main (v '{path}'): {', '.join(dcmp.left_only)}")
    if dcmp.right_only:
        output.append(f"Len v Nexus-Pokrok (v '{path}'): {', '.join(dcmp.right_only)}")
    if dcmp.diff_files:
        output.append(f"Rozdielne súbory (v '{path}'): {', '.join(dcmp.diff_files)}")
    
    for sub_dcmp_name, sub_dcmp in dcmp.subdirs.items():
        if sub_dcmp_name not in ignore:
            get_diff(sub_dcmp, os.path.join(path, sub_dcmp_name))

get_diff(dcmp, "/")

with open(r"C:\Users\Peto\Desktop\PICA\FUTURE_CLEAN_24\Nexus-Pokrok\scratch\diff_output.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(output))

print("Done")
