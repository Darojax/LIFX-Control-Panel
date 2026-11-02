from setuptools import setup, find_packages

from lifx_control_panel._constants import VERSION

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="lifx_control_panel",
    version=str(VERSION),
    description="An open source application for controlling your LIFX brand lights",
    url="https://github.com/Darojax/LIFX-Control-Panel",
    author="Sawyer McLane",
    author_email="samclane@gmail.com",
    license="MIT",
    packages=find_packages(),
    zip_safe=False,
    scripts=["lifx_control_panel/__main__.pyw"],
    include_package_data=True,
    keywords=["lifx", "iot", "smartbulb", "smartlight", "lan", "application"],
    install_requires=[
        "keyboard",
        "mouse",
        "Pillow",
        "lifxlan",
        "bitstring<4",
        "numpy",
        "mss==10.1.0",
        "pystray",
        "pywin32; sys_platform == 'win32'",
    ],
    extras_require={"audio": ["pyaudio"]},
    python_requires=">=3.12",
    download_url=(
        ("https://github.com/Darojax/LIFX-Control-Panel/archive/" + str(VERSION))
        + ".tar.gz"
    ),
    long_description_content_type="text/markdown",
    long_description=long_description,
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        "Development Status :: 5 - Production/Stable",
        # Indicate who your project is intended for
        "Intended Audience :: End Users/Desktop",
        "Natural Language :: English",
        "Operating System :: Microsoft :: Windows :: Windows 10",
        "Topic :: Home Automation",
        # Pick your license as you wish (should match "license" above)
        "License :: OSI Approved :: MIT License",
        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        "Programming Language :: Python :: 3.12",
    ],
)
