import os
from dotenv import load_dotenv

load_dotenv()

# Valor seguro por defecto para evitar que el cliente explote si falta .env.
# En producción, define CYFER_KEY en tu .env.
try:
    key = int(os.getenv("CYFER_KEY", "0"))
except ValueError:
    key = 0


def cifrar_texto(texto, llave=key):
    """Desplaza cada carácter hacia adelante según la llave."""
    if texto is None:
        return ""

    resultado = ""
    for caracter in str(texto):
        nuevo_codigo = ord(caracter) + llave
        resultado += chr(nuevo_codigo)
    return resultado


def descifrar_texto(texto_cifrado, llave=key):
    """Desplaza cada carácter hacia atrás según la llave."""
    if texto_cifrado is None:
        return ""

    resultado = ""
    for caracter in str(texto_cifrado):
        nuevo_codigo = ord(caracter) - llave
        resultado += chr(nuevo_codigo)
    return resultado
