"""
py.test 'xdist' plugin for distributed testing and loop-on-failing modes. 

See http://codespeak.net/pytest-xdist for documentation and, after
installation, "py.test -h" for the new options. 
"""

from setuptools import setup

setup(
    name="pytest-xdist",
    version="1.0",
    description='py.test figleaf coverage plugin',
    long_description=__doc__,
    license='GPLv2 or later',
    author='holger krekel and contributors',
    author_email='py-dev@codespeak.net,holger@merlinux.eu', 
    url='http://bitbucket.org/hpk42/pytest-figleaf',
    platforms=['linux', 'osx', 'win32'],
    packages = ['xdist'],
    entry_points = {'pytest11': ['xdist = xdist.plugin'],},
    zip_safe=False,
    install_requires = ['execnet', 'py>=1.2.0a1'],
    classifiers=[
    'Development Status :: 4 - Beta',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: GNU General Public License (GPL)',
    'Operating System :: POSIX',
    'Operating System :: Microsoft :: Windows',
    'Operating System :: MacOS :: MacOS X',
    'Topic :: Software Development :: Testing',
    'Topic :: Software Development :: Quality Assurance',
    'Topic :: Utilities',
    'Programming Language :: Python',
    ],
)
