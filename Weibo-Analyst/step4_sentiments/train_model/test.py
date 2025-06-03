from snownlp import sentiment, SnowNLP

# 不加载自定义模型，使用默认模型
text = "这个商品真的很差劲，服务态度也很恶心"
print("默认模型评分:", SnowNLP(text).sentiments)

# 加载你自己的模型
sentiment.load('/workspace/step4_sentiments/train_model/my_sentiment.marshal')
print("自定义模型评分:", SnowNLP(text).sentiments)
