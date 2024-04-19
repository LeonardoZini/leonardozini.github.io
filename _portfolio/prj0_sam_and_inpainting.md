---
title: "Segment Anything & InPainting"
excerpt: "A CV pipeline that fuse together image segmentation and inpainting.<br/><img src='/images/segmentation.png'>"
collection: portfolio
---

Computer vision pipeline developed in occasion of my curricular internship at AImageLab for my master thesis.
This thesis work presents an exploration of a novel combined approach to segmentation, classification, and inpainting in a computer vision pipeline. The goal of the presented pipeline is to automatically segment certain classes in an image while giving the possibility to remove any object from the scene that has been previously classified. In detail, this work exploits two different foundation models, CLIP and Segment-Anything (SAM). The pipeline starts with the adaptation of SAM to automatically segment a set of a priori known classes. To achieve this, a new heatmap generator model has been presented, called ResNetDec. The adaptation also includes a method of sampling based on clustering. To remove objects from the scene, the work will be presented as a comparison between two inpainting models that respect the minimum requirements. In the end, a novel classification approach has been presented, based on the alignment of the CLIP and SAM visual encoder space, to both classify and segment in an open vocabulary setting without the cost of having two foundation models loaded in memory.