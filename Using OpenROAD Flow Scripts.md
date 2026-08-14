&#x09;Congratulations on a successful local installation of OpenROAD Flow Scripts! The following guide has been constructed using a local install, so commands may not transfer directly to OpenROAD flow scripts instances run using Docker or Bazel.



DESIGN FLOW TEST RUN



&#x09;We will conduct the full RTL to GDSII design flow using the example "spm" design in the GitHub documentation. The goal is familiarization with setting up the scripts supervising the flow.



1\. Create the Verilog source files directory based on the top module name. First, we navigate into the "flow" folder, followed by the "designs" and source "src" folder. Make a directory called "spm"



&#x09;cd flow/designs/src

&#x09;mkdir spm



2\. Create the source RTL verilog file inside the new directory "spm". 

&#x09;

&#x09;vi spm.v

&#x09;

&#x20;  Go to the following link and copy the following code into the new spm.v file.



&#x09;https://raw.githubusercontent.com/The-OpenROAD-Project/OpenLane/master/designs/spm/src/spm.v

&#x09;

&#x20;  To exit the vim editor window in Linux , hit the "esc" button, followed by typing ":wq". 



3\. We will now make a matching "spm" directory inside the folder of our desired design package. In this case that path should be "**designs/gf180"** This is where we will place the configuration file. 



&#x09;	

&#x09;cd flow/designs/gf180

&#x09;mkdir spm

&#x09;cd spm



4\. Create config.mk to define design configuration.



&#x09;vi config.mk



&#x20;  Copy the following into the new config.mk file:



&#x20;      "export PLATFORM         = gf180



&#x09;export DESIGN\_NAME      = spm



&#x09;export VERILOG\_FILES    = $(sort $(wildcard ./designs/src/$(DESIGN\_NICKNAME)/\*.v))

&#x09;export SDC\_FILE         = ./designs/$(PLATFORM)/$(DESIGN\_NICKNAME)/constraint.sdc



&#x09;export CORE\_UTILIZATION = 40

&#x09;export PLACE\_DENSITY    = 0.60



&#x09;export TNS\_END\_PERCENT  = 100"



&#x20;  Once again, use the "esc" button and type ":wq" to exit.



5\. In the same folder as the config.mk file, we will define our SDC constraints using a constraint file.



&#x09;cd flow/designs/gf180/spm

&#x09;vi constraint.sdc



&#x20;  Copy the following into the new constraint.sdc file:



&#x20;      "current\_design spm



&#x09;set clk\_name  core\_clock

&#x09;set clk\_port\_name clk

&#x09;set clk\_period 10

&#x09;set clk\_io\_pct 0.2



&#x09;set clk\_port \[get\_ports $clk\_port\_name]



&#x09;create\_clock -name $clk\_name -period $clk\_period  $clk\_port



&#x09;set non\_clock\_inputs \[lsearch -inline -all -not -exact \[all\_inputs] $clk\_port]



&#x09;set\_input\_delay  \[expr $clk\_period \* $clk\_io\_pct] -clock $clk\_name $non\_clock\_inputs

&#x09;set\_output\_delay \[expr $clk\_period \* $clk\_io\_pct] -clock $clk\_name \[all\_outputs]"



&#x20;   Note: Update only current\_design, clk\_port\_name and clk\_period as per design requirements. Do not modify the remaining values for the default template.



6\. We will now navigate into the base "flow" folder to modify the existing "Makefile" to specify which design configuration we want to put through the design flow.



&#x09;cd flow

&#x09;vi Makefile



&#x20;  Copy the following line into the Makefile. Notice that unused design configs are commented out (#), so make sure our design config is not commented out.



&#x09;DESIGN\_CONFIG=./designs/gf180/spm/config.mk



&#x20;  Exit the Makefile. We should still be in the base "flow" folder. Now run the design config using the following command:



&#x09;make



7\. If everything has been done correctly, there should be a long flash of text indicating that the design flow is working. The design flow is finished once a final design chart is shown and the command prompt is returned. We can also view the final GDSII layout by executing:



&#x09;make gui\_final



&#x20;  A new OpenROAD GUI window should appear with the silicon ready design traces on it.

&#x09;



