import struct


def print_binary_as_integers(file_name):
    """ Useful tool for inspecting data you assume or suspect is integers. """
    with open(file_name, 'rb') as file:
        offset = 0
        data = file.read(4)
        while data != -1:
            try:
                integer = struct.unpack('<i', data)
            except struct.error:
                print('Less than 4 bytes remaining.')
                return
            print('{} | {} | {}'.format(offset, hex(offset), integer))
            data = file.read(4)
            offset += 4
