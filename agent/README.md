# agent

`parser.py` turns a typed clearance question into a structured request with fixed patterns and the SKOS
vocabularies; `model_parser.py` can ask Claude on Bedrock for parts the parser missed and checks the answer
against the same vocabularies. Gate 3 runs the agent with Strands on ECS Fargate.
