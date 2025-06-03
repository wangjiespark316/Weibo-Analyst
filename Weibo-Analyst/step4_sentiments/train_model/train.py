#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from snownlp import sentiment

#sentiment.train('negative_dict.txt', 'positive_dict.txt')
sentiment.train('/workspace/step4_sentiments/train_model/negative_dict.txt', '/workspace/step4_sentiments/train_model/positive_dict.txt')
sentiment.save('/workspace/step4_sentiments/train_model/my_sentiment.marshal')