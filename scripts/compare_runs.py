import sys
from validation.reproducibility import sha256_file

if __name__ == "__main__":
    print([sha256_file(path) for path in sys.argv[1:]])

