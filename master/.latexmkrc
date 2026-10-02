# Any latexmk run in master/ (including `make watch`) keeps the named PDF
# byte-identical to resume.pdf. Name matches profile.json.
$success_cmd = 'cp -f %D Joseph_Yu_resume.pdf';
