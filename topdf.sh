#!/bin/bash

jupyter nbconvert --to=latex --TagRemovePreprocessor.remove_cell_tags='{"remove_cell"}' --template=revtex_nocode.tplx Capstone_Week5.ipynb
pdflatex Capstone_Week5.tex
pdflatex Capstone_Week5.tex
pdflatex Capstone_Week5.tex

rm *.bbl *.aux *.blg *.log *.out *Notes.bib #*.tex
