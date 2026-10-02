.PHONY: all master app watch clean internships-install internships-uninstall internships-now internships-dry internships-report internships-gc internships-dashboard internships-backfill

all: master

master: master/resume.pdf

master/resume.pdf: master/resume.tex
	cd master && latexmk -pdf -interaction=nonstopmode resume.tex
	cp -f master/resume.pdf master/Joseph_Yu_resume.pdf

watch:
	cd master && latexmk -pdf -pvc -interaction=nonstopmode resume.tex

# make app DIR=applications/acme-swe
app:
	cd "$(DIR)" && latexmk -pdf -interaction=nonstopmode resume.tex
	python3 -c "from pathlib import Path; import sys; sys.path.insert(0,'.cursor/skills/tailor-resume/scripts'); from check_resume import submit_pdf_path; print(submit_pdf_path(Path('$(DIR)'), promote=True))"

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

internships-backfill:
	./automation/run.sh --backfill

internships-dashboard:
	./automation/run.sh --dashboard

clean:
	cd master && latexmk -C
	rm -f master/Joseph_Yu_resume.pdf
	@find applications \( -name '*.aux' -o -name '*.log' -o -name '*.out' -o -name '*.fdb_latexmk' -o -name '*.fls' -o -name '*.synctex.gz' \) -delete
