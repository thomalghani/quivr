import json
from typing import AsyncIterable
from uuid import UUID

from langchain_community.chat_models import ChatLiteLLM
from langchain_community.utilities import SQLDatabase
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from modules.brain.integrations.SQL.SQL_connector import SQLConnector
from modules.brain.knowledge_brain_qa import KnowledgeBrainQA
from modules.brain.repository.integration_brains import IntegrationBrain
from modules.chat.dto.chats import ChatQuestion



class SQLBrain(KnowledgeBrainQA, IntegrationBrain):
    """This is the Notion brain class. it is a KnowledgeBrainQA has the data is stored locally.
    It is going to call the Data Store internally to get the data.

    Args:
        KnowledgeBrainQA (_type_): A brain that store the knowledge internaly
    """

    uri: str = None
    db: SQLDatabase = None
    sql_connector: SQLConnector = None

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(
            **kwargs,
        )
        self.sql_connector = SQLConnector(self.brain_id, self.user_id)

    def get_schema(self, _):
        return self.db.get_table_info()

    def run_query(self, query):
        return self.db.run(query)

    def get_chain(self):
        template = """Based on the table schema below, write a SQL query that would answer the user's question:
        
        Schema: {schema}
        Question: {question}
        
        Return SQL Query Only based on the given schema, no yapping

        """
        prompt = ChatPromptTemplate.from_template(template)

        self.db = SQLDatabase.from_uri(self.sql_connector.credentials["uri"])

        api_base = None
        if self.brain_settings.ollama_api_base_url and self.model.startswith("ollama"):
            api_base = self.brain_settings.ollama_api_base_url


        model = ChatLiteLLM(model=self.model, api_base=api_base, temperature=0)

        print("the schema",self.get_schema(""))

        sql_response = (
            RunnablePassthrough.assign(schema=self.get_schema)
            | prompt
            | model.bind(stop=["\nSQLResult:"])
            | StrOutputParser()
        )

        template = """Based on the table schema below, question, sql query, and sql response, write a natural language response and the query that was used to generate it.:
            {schema}

            Question: {question}
            SQL Query: {query}
            SQL Response: {response}"""


        # template = """
        # Based on these context below, please answer the question

        # Question: {question}
        # Context: {response}
        
        # """

        prompt_response = ChatPromptTemplate.from_template(template)

        print("promt response", prompt_response)

        def rq(x):
            print("lalalalala", x["query"])
            print("lalalalala", x)
            return self.db.run(x["query"])

        full_chain = (
            RunnablePassthrough.assign(query=sql_response).assign(
                schema=self.get_schema,
                response=lambda x: self.db.run(x["query"].replace('\\', '')),
                # response=lambda x: rq(x),
            )
            | prompt_response
            | model
        )

        return full_chain

    async def generate_stream(
        self, chat_id: UUID, question: ChatQuestion, save_answer: bool = True
    ) -> AsyncIterable:

        conversational_qa_chain = self.get_chain()
        transformed_history, streamed_chat_history = (
            self.initialize_streamed_chat_history(chat_id, question)
        )
        response_tokens = []

        async for chunk in conversational_qa_chain.astream(
            {
                "question": question.question,
            }
        ):
            response_tokens.append(chunk.content)
            streamed_chat_history.assistant = chunk.content
            yield f"data: {json.dumps(streamed_chat_history.dict())}"

        self.save_answer(question, response_tokens, streamed_chat_history, save_answer)
