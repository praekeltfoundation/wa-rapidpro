#!/usr/bin/env python
# -*- coding: utf-8 -*-


try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup


with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('VERSION') as fp:
    version = fp.read().strip()

setup(
    name='warapidpro',
    version=version,
    description="warapidpro",
    long_description=readme,
    author="Simon de Haan",
    author_email='simon@praekelt.org',
    url='https://github.com/praekeltfoundation/wa-rapidpro',
    packages=[
        'warapidpro',
    ],
    package_dir={'warapidpro':
                 'warapidpro'},
    include_package_data=True,
    install_requires=[],
    zip_safe=False,
    keywords='warapidpro',
    classifiers=[
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.6',
    ]
)
