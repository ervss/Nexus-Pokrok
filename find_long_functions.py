import ast
import os

def find_python_files(directory):
    """Recursively finds all Python files in the given directory."""
    python_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                python_files.append(os.path.join(root, file))
    return python_files

def get_function_definitions(filepath):
    """Identifies function definitions in a Python file using AST."""
    functions = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(node)
    except Exception:
        pass
    return functions

def get_function_length(node):
    """Calculates the line count of a function definition."""
    if hasattr(node, "end_lineno") and hasattr(node, "lineno"):
        return node.end_lineno - node.lineno + 1
    return 0

if __name__ == "__main__":
    THRESHOLD = 50
    files = find_python_files(".")
    for f in files:
        funcs = get_function_definitions(f)
        for func in funcs:
            length = get_function_length(func)
            if length > THRESHOLD:
                print(f"Long function found: {f} -> {func.name} ({length} lines)")
