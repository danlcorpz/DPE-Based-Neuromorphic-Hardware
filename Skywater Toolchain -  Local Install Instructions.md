&#x09;The following guide is for installing the automated RTL to GDSII toolchain, OpenRoad Flow Scripts, targeting System Verilog to Silicon using the Skywater 130nm PDK. It assumes that you, like me, are complete beginners and know very little about the process behind semiconductor design. It is recommended to try the Docker Image process before a local installation as a Docker Image is portable, and easier to work with than a local installation. However, unresolvable image and system incompatibilities may appear during design flow testing, and a local installation will be necessary.



&#x09;Many steps are taken to convert System Verilog code into manufacturable photomasks. The design flow starts with RTL (Verilog code), followed by synthesis, floorplanning, placement, clock tree synthesis, routing, and finishing. What is left after the design flow is the final GDSII layout, ready to be sent out to a foundry and etched onto a wafer. Many open source tools take care of different parts of the design flow, including Yosys for synthesis, OpenROAD for floorplanning, placement, clock tree synthesis, and routing, and KLayout for finishing layouts (touchups, edits, and checks). Each tool stands alone, but are still used together to complete the open source design flow. OpenRoad Flow Scripts (OFRS) is an open source project that seeks to automate the interaction and data flow between the individual open source tools using scripts. Additionally, it packages all the tools and other dependencies in the toolchain in one install, making it extremely convenient compared to comparing compatibilities between versions and hand compiling. This makes the RTL to GDSII design process smoother and more hands off, and unifies the toolchain into one cohesive black-box.



&#x09;ORFS only runs on Linux, so most of the work is done through a command line interface (CLI). So it will be helpful to know basic Unix commands such as "pwd", "ls", and "cd" to navigate the file tree without a graphical user interface (GUI). It is important to note that small mistakes during installation can be extremely time costly, as errors can be hard to trace through a CLI. The hope of this guide is to simplify the process to make it as smooth and understandable as possible.



PREREQUISITES



1\. Install Windows Subsystem for Linux (WSL)

&#x09;The Windows Subsystem for Linux is a CLI program that allows us to run a full Linux environment inside Windows. Going forward, we will be working

&#x09;primarily with WSL.

&#x09;a. Follow the instructions on the following webpage to install WSL. We want to install Ubuntu 22.04.



&#x09;	https://learn.microsoft.com/en-us/windows/wsl/install



&#x09;b. You can check the version of your WSL distro using the following command:



&#x09;	lsb\_release -a



2\. Install Docker Desktop

&#x09;While Docker is not needed for this process, the GitHub documentation lists it as a prerequisite, and I have not tested the entire installation process without it. Docker is used to package applications and all of 	their required dependencies into a lightweight, and isolated unit called a "container". This is helpful to us, as one predefined container template 	or "image" can be installed and ran instead of having to sort through, install, and 	troubleshoot compatability between all the tools in the 	chain.



&#x09;a. Download Docker Desktop from the following link. A personal license is free!



&#x09;	https://docs.docker.com/desktop/setup/install/windows-install/



&#x09;b. Open Docker Desktop and change the following Settings in the GUI to allow WSL to use Docker:



&#x09;	General > Use the WSL 2 Based engine (should be default selection)

&#x09;	Resources > WSL integration > Enable integration with my default WSL distro. Select “Ubuntu-22.04”



3\. Search for an app in the toolbar named "Ubuntu 22.04 LTS”. Open it. This is how we can access WSL.



&#x09;a. Run the following command to set up Python in Ubuntu:



&#x09;	sudo apt-get update; sudo apt-get upgrade; sudo apt install -y build-essential python3 python3-venv python3-pip make



&#x09;b. Execute the following command to verify Docker is running:



&#x09;	sudo docker run hello-world

&#x09;

&#x09;   You should see: Hello from Docker! This message shows that your installation appears to be working correctly.



If everything is successful up to this point, congratulations! You are now ready to follow the ORFS installation guide as you have configured a Linux system with necessary dependencies.



ORFS LOCAL INSTALLATION



1\. Run the following command to clone ORFS the repository:



&#x09;git clone --recursive https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts



2\. Navigate into the "etc" folder of the newly cloned repository using:



&#x09;cd OpenROAD-flow-scripts



&#x09;cd etc



3\. Our path should now be "\~/OpenROAD-flow-scripts/etc". Install the necessary dependencies for local ORFS using the following command:



&#x09;sudo ./DependencyInstaller.sh -all



4\. Once the dependency install is finished, we will go back a folder and build the ORFS locally.

&#x09;

&#x09;cd ..

&#x09;sudo ./build\_openroad.sh -o

&#x09;

&#x20;  Warning: The build command will use all available threads to compile the repository. If that is an issue, use the following command to limit the number of threads used, where N is the number of threads to be used instead:

&#x09;

&#x09;sudo ./build\_openroad.sh -o --threads N



&#x20;  This process can take 30-60 minutes, and the log may fill up completely and stop giving updates for a time. Be patient! It will report DONE when finished.



5\. Once the installation process finishes, we want to verify everything is working with the following commands. The -help commands should yield a list of commands for the programs. If so, the tools are working correctly.



&#x09;source ./env.sh				// Should output a path pointing to the tools!

&#x09;yosys -help				// Should yield a list of commands!

&#x09;yosys -m slang -p "slang\_version"	// Should yield a little ASCII box with credits and info inside!

&#x09;openroad -help				// Should yield a list of commands!



6\. The design flow will be tested now using the following commands. Running "make" in the "flow" folder should yield the RTL to GDSII design overview using an example file. Make

&#x20;  sure there are no errors in the terminal after running the make command!



&#x09;cd flow

&#x09;make



7\. If everything is working correctly, you should see a chart with log, ext, elapsed/s, Peak, Memoryu, and shalsum result as headings.



