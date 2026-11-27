from setuptools import find_packages, setup

package_name = "dream1_piper_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/station.launch.py"]),
        ("share/" + package_name + "/config", ["config/servo.yaml"]),
        ("share/" + package_name + "/description", ["description/piper.urdf", "description/piper_bimanual.srdf"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={"console_scripts": ["station_bridge = dream1_piper_ros.station_bridge:main"]},
)
