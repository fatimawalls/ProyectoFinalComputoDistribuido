
import os
from dotenv import load_dotenv

load_dotenv()

# Ahora puedes acceder a ellas con os.getenv()
key = os.getenv("CYFER_KEY")

def cifrar_texto(texto, llave=int(key)):
    """Desplaza cada carácter hacia adelante según la llave."""
    resultado = ""
    for caracter in texto:
        nuevo_codigo = ord(caracter) + llave
        resultado += chr(nuevo_codigo)
    return resultado

def descifrar_texto(texto_cifrado, llave=int(key)):
    """Desplaza cada carácter hacia atrás según la llave."""
    resultado = ""
    for caracter in texto_cifrado:
        nuevo_codigo = ord(caracter) - llave
        resultado += chr(nuevo_codigo)
    return resultado

