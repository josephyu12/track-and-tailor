.PHONY: all master app watch clean internships-install internships-uninstall internships-now internships-dry internships-report internships-gc internships-dashboard

all: master

master: master/resume.pdf

master/resume.pdf: master/resume.tex
	cd master && latexmk -pdf -interaction=nonstopmode resume.tex

watch:
	cd master && latexmk -pdf -pvc -interaction=nonstopmode resume.tex

# make app DIR=applications/acme-swe
app:
	cd "$(DIR)" && latexmk -pdf -interaction=nonstopmode resume.tex

internships-install:
	chmod +x automation/install.sh automation/uninstall.sh automation/run.sh
	./automation/install.sh

internships-uninstall:
	./automation/uninstall.sh

internships-now:
	./automation/run.sh

internships-dry:
	./automation/run.sh --dry-run

internships-report:
	./automation/run.sh --report-only

internships-gc:
	./automation/run.sh --cleanup

internships-dashboard:
	./automation/run.sh --dashboard

clean:
	cd master && latexmk -C
	@find applications -name '*.pdf' -o -name '*.aux' -o -name '*.log' -o -name '*.out' -o -name '*.fdb_latexmk' -o -name '*.fls' | xargs rm -f
