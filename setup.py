from setuptools import setup

setup(name='undocker3',
        author = 'Lars Kellogg-Stedman',
        author_email = 'lars@oddbit.com',
        license = "GPL v3",
        version='6',
        description='Unpack docker images',
        url='http://github.com/coaic/undocker3',
        py_modules=['undocker3'],
        entry_points={
            'console_scripts': [
                'undocker3 = undocker3:main',
                ],
            }
        )
