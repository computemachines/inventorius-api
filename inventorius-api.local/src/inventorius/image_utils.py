def assert_png(filename):
  """Ensure the file at a give path has the PNG magick-number
  header.  Throw an `AssertionError` if it does not match.
  """
  PNG_HEADER = [
      0x89, 0x50, 0x4E, 0x47,
      0x0D, 0x0A, 0x1A, 0x0A
  ]
  with open(filename, 'rb') as fd:
      file_header = list(fd.read(8))
  assert file_header == PNG_HEADER
