from setuptools import setup, find_packages

from daemonx import __version__ as version


name = 'daemonx'


setup(
    name=name,
    version=version,
    description='Daemon',
    author_email='glange@rackspace.com',
    packages=find_packages(exclude=['test_qork', 'bin']),
    test_suite='nose.collector',
    classifiers=[
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 2.6',
        'Environment :: No Input/Output (Daemon)',
        ],
    # removed for better compat
    install_requires=[],
    scripts=[],
    )
