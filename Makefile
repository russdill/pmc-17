GEN_SYM=\
	symbols/generated/ft2232h-1.sym \
	symbols/generated/rclamp0502a-1.sym \
	symbols/generated/tdp4e002-1.sym \
	symbols/generated/adg732-1.sym \
	symbols/generated/lm3671-1.sym \
	symbols/generated/ntb0104-1.sym

PRJ=pmc
PCB=~/src/pcb/_install/bin/pcb
PCB_BATCH=~/src/pcb/_install/bin/pcb
GSCH2PCB=~/src/pcb/gsch2pcb

SCHEMATICS=$(PRJ)_1.sch $(PRJ)_2.sch $(PRJ)_3.sch $(PRJ)_4.sch $(PRJ)_5.sch $(PRJ)_6.sch $(PRJ)_7.sch

all: $(PRJ)_front.png $(PRJ)_back.png $(PRJ)_schematic.pdf $(PRJ).pdf gerber $(PRJ).bom gerber.png
	mkdir -p output
	cp $(PRJ)_front.png $(PRJ)_back.png $(PRJ)_schematic.pdf $(PRJ).pdf $(PRJ).bom output
	cp *.gbr *.cnc output

$(PRJ)_schematic.pdf: $(PRJ)_1.ps $(PRJ)_2.ps $(PRJ)_3.ps $(PRJ)_4.ps $(PRJ)_5.ps $(PRJ)_6.ps $(PRJ)_7.ps
	gs -q -dQUIET -dBATCH -dNOPAUSE \
		-sDEVICE=pdfwrite -sOutputFile="$@" $^

.PHONY: png_schematic
png_schematic: $(PRJ)_1.png $(PRJ)_2.png $(PRJ)_3.png $(PRJ)_4.png $(PRJ)_5.png $(PRJ)_6.png $(PRJ)_7.png

gerber.png: gerber
	gerbv -p $(PRJ).gvp -o $@ -x png -a -D 400

project: $(PRJ).project $(SCHEMATICS)
	$(GSCH2PCB) -s -f -d ./packages $<

symbols: $(GEN_SYM)

%.sym: %.symdef
	djboxsym "$<" > "$@"

%.ps: %.sch
	gschem -p -o$@ -sprint.scm $<

%.png: %.sch
	gschem -p -o$@ -simage.scm $<

#$(PRJ).zip: $(PRJ).pcb Makefile
#	tmp=$(shell mktemp -d); cd $$tmp; \
#	$(PCB) -x gerber --verbose --all-layers $(PWD)/$<

$(PRJ).zip: gerber Makefile
	zip $@ $(PRJ).{{bottom{,mask,silk},top{,mask,silk},group[1-2],outline,}.gbr,plated-drill.cnc}

oshpark.zip: gerber
	@-rm -rf oshpark/
	mkdir oshpark
	cp $(PRJ).top.gbr oshpark/Top\ Layer.ger
	cp $(PRJ).bottom.gbr oshpark/Bottom\ Layer.ger
	cp $(PRJ).topmask.gbr oshpark/Top\ Solder\ Mask.ger
	cp $(PRJ).bottommask.gbr oshpark/Bottom\ Solder\ Mask.ger
	cp $(PRJ).outline.gbr oshpark/Board\ Outline.ger
	cp $(PRJ).topsilk.gbr oshpark/Top\ Silk\ Screen.ger
	cp $(PRJ).bottomsilk.gbr oshpark/Bottom\ Silk\ Screen.ger
	./merge_drill.sh $(PRJ).{un,}plated-drill.cnc > oshpark/Drills.xln
	-rm oshpark.zip
	cd oshpark && zip ../oshpark.zip *.ger *.xln

.$(PRJ).nopaste.pcb: $(PRJ).pcb $(PRJ).dnp.bom no_paste.sh
	cp $< $@
	sed "s/--/$(VERSION)/" -i $@
	bash -c "$(PCB_BATCH) --action-script <(./no_paste.sh $(PRJ).dnp.bom) $@"

.PHONY: gerber
gerber: .$(PRJ).nopaste.pcb
	$(PCB) -x gerber --verbose --metric --all-layers --gerberfile $(PRJ) $<

.PHONY: png
png: $(PRJ)_front.png $(PRJ)_back.png

%.ps: %.pcb Makefile
	$(PCB) -x ps --ps-color --align-marks --media Letter --psfade .5 --psfile $@ $<

%.pdf: %.ps
	ps2pdf $< $@

$(PRJ).dnp.bom: $(PRJ)_*.sch
	gnetlist -g bom2 $^ -o $@

$(PRJ).bom: $(PRJ).dnp.bom
	grep -v ".*:.*:.*:.*:1:.*" $< | grep -v ".*:NoConnection:.*:.*:.*:.*" > $@

%.xy: %.pcb
	$(PCB_BATCH) -x bom --bomfile /dev/null $<

DPI=500
COLOR=purple
$(PRJ)_front.png: $(PRJ).pcb Makefile
	$(PCB_BATCH) -x png --outfile $@ --dpi $(DPI) --use-alpha --photo-mode --photo-mask-colour $(COLOR) --photo-plating gold $<

$(PRJ)_back.png: $(PRJ).pcb Makefile
	$(PCB_BATCH) -x png --outfile $@ --dpi $(DPI) --use-alpha --photo-mode --photo-mask-colour $(COLOR) --photo-plating gold --photo-flip-x $<


clean:
	-rm -f *.ps *.pdf *.gbr *.cnc *.png

