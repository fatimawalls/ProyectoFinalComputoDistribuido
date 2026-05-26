def cifrar_texto(texto, llave):
    """Desplaza cada carácter hacia adelante según la llave."""
    resultado = ""
    for caracter in texto:
        nuevo_codigo = ord(caracter) + llave
        resultado += chr(nuevo_codigo)
    return resultado

def descifrar_texto(texto_cifrado, llave):
    """Desplaza cada carácter hacia atrás según la llave."""
    resultado = ""
    for caracter in texto_cifrado:
        nuevo_codigo = ord(caracter) - llave
        resultado += chr(nuevo_codigo)
    return resultado

llave_numerica = 5
mensaje = "¡Hola Mundo 123!"

encriptado = cifrar_texto(mensaje, llave_numerica)
print(f"Texto cifrado: {encriptado}")

desencriptado = descifrar_texto(encriptado, llave_numerica)
print(f"Texto original: {desencriptado}")