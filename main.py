import config as config
import json
import numpy as np
import redis
from catsim.estimation import *  # estimation package contains different proficiency estimation methods
from catsim.initialization import *  # initialization package contains different initial proficiency estimation strategies
from catsim.selection import *  # selection package contains different item selection strategies
from catsim.stopping import *  # stopping package contains different stopping criteria for the CAT
from distutils.util import strtobool
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

CATModule = FastAPI()  # Used for REST API

r = redis.Redis(  # Used for DataStorage
    host=config.redis["host"],
    port=config.redis["port"],
    db=config.redis["db"],
    password=config.redis["password"]
)


# Question object for API --> used for quiz creation
class QuestionAPI(BaseModel):
    id: int
    discrimination: Optional[float] = 1.0
    difficulty: float
    pseudoGuessing: Optional[float] = 0.0
    upperAsymptote: Optional[float] = 1.0


# Quiz object for API --> Used for quiz creation
class QuizAPI(BaseModel):
    quizId: Optional[int]
    maxNumberOfQuestions: Optional[int] = config.defaultAdaptiveQuiz["maxNumberOfQuestions"]
    minMeasurementAccuracy: Optional[float] = config.defaultAdaptiveQuiz["minMeasurementAccuracy"]
    inputProficiencyLevel: Optional[float] = config.defaultAdaptiveQuiz["inputProficiencyLevel"]
    questionSelector: Optional[str] = config.defaultAdaptiveQuiz["questionSelector"]
    competencyEstimator: Optional[str] = config.defaultAdaptiveQuiz["competencyEstimator"]
    questions: List[QuestionAPI] = []


# Answer object for API --> Used for sending the answer(isCorrect) of the current question of the quiz in the request
class AnswerAPI(BaseModel):
    quizId: int
    isCorrect: Optional[float] = None


# Question object for API --> Used to send the next question as a response
class NextQuestionAPI(BaseModel):
    quizId: int
    questionId: Optional[int] = None
    measurementAccuracy: float
    currentCompetency: float
    quizFinished: bool


# Result object for API --> Used to send the quiz result in the response.
class ResultAPI(BaseModel):
    quizId: int
    quizFinished: bool
    currentCompetency: float
    measurementAccuracy: float
    maxNumberOfQuestions: int
    administeredQuestions: List[
        QuestionAPI] = []  # contains all questions administered during the quiz including their difficulty
    responses: List[float] = []  # contains the given answers for the administeredQuestions


# QuizID object for API
class QuizIdAPI(BaseModel):
    quizId: int


# --------------- REST CALLS ---------------

@CATModule.post("/quiz", status_code=201, summary="Create a new quiz", tags=["quiz"])
async def api_create_quiz(quizAPI: QuizAPI):
    """
    Create a new quiz, this can either be adaptive or classic:

    Adaptive Quiz:
    - **quizId**: Not necessary, will be replaced by an automatically created unique ID.
    - **maxNumberOfQuestions**: The maximum amount of questions for the quiz. This will be used as a stopping criteria for the exam.
    - **minMeasurementAccuracy**: The threshold for the Standard Error of Estimation. This will be used as a stopping criteria for the exam.
    - **questionSelector**: Defines how the next question is selected. 'maxInfoSelector' represents the Maximum Information Selector (https://douglasrizzo.com.br/catsim/selection.html#catsim.selection.MaxInfoSelector) for adaptive quizzes. This is also the default.
    - **competencyEstimator**: Defines how the competency is calculated. 'differentialEvolutionEstimator' is the default Estimator, no others are currently implemented.
    - **questions**: List of **possible quiz questions** containing their id and configuration (discrimination, difficulty, pseudoGuessing, upperAsymptote). id and difficulty are the only non-optional parameters. Example Value: {"id":1,"difficulty": -1.760337722}

    Example request body to create an adaptive quiz:<br>
    {<br>
        "questions": [<br>
            {"id":450,"difficulty": 3.087229159},<br>
            {"id":12,"difficulty": -0.21594258},<br>
            {"id":300,"difficulty": -0.481329825}],<br>
        "maxNumberOfQuestions": 20,<br>
        "minMeasurementAccuracy": 0.8,<br>
        "questionSelector": "maxInfoSelector"<br>
    }

    Classic Quiz:
    - **quizId**: Not necessary, will be replaced by an automatically created unique ID.
    - **maxNumberOfQuestions**: Not necessary since the number of quiz questions is determined by the length of the questions list.
    - **minMeasurementAccuracy**: Not necessary since a classic quiz is finished when all questions are delivered.
    - **questionSelector**: Defines how the next question is selected. 'linearSelector' represents the Selector for a non-adaptive Test (https://douglasrizzo.com.br/catsim/selection.html#catsim.selection.LinearSelector).
    - **competencyEstimator**: Defines how the competency is calculated. Non-adaptive tests calculate the overall percentage of correct answers as competency.
    - **questions**: **Ordered** list of **all questions** for the quiz (containing their id and difficulty).

    Example request body to create a classic quiz:<br>
    {<br>
        "questions": [<br>
            {"id":1,"difficulty": 3.087229159},<br>
            {"id":2,"difficulty": -0.21594258},<br>
            {"id":3,"difficulty": -0.481329825}],<br>
        "questionSelector": "linearSelector"<br>
    }

    Response:
    - **quizId**: Unique ID of the quiz.
    - **Other**: The other contents of the response represent the configuration of the quiz
    """
    # TODO validate maxNumberOfQuestions -> It must be less or equal than the number of given questions
    return create_quiz(quizAPI)


@CATModule.get("/quiz/question", summary="Get the next question of quiz with ID", tags=["question"])
async def api_get_next_question(answer: AnswerAPI):
    """
    Get the next question of the quiz by quizID and also send the answer to the previous question:

    - **quizId**: Unique ID of the quiz (was returned by the POST quiz request)
    - **isCorrect**: Correctness of the previous question. In the case of an adaptive quiz: 1.0 if the previous answer was correct, <1.0 if the previous answer was incorrect. In the case of a non-adaptive quiz, this represents the percentage of correctness of the answer. When requesting the first quiz question this will be ignored.

    Response:
    - **quizId**: Unique ID of the quiz.
    - **questionId**: The ID for the next question to be administered. Not set if quizFinished=true.
    - **measurementAccuracy**: Standard Estimation Error of the current competency.
    - **currentCompetency**: Describes the proficiency of the examinee.
    - **quizFinished**: True if the quiz is already finished.
    """
    if (not (quizIdExists(answer.quizId))):
        raise HTTPException(status_code=404, detail="Quiz with id " + str(answer.quizId) + " not found!")
    if (strtobool(r.get(get_rPrefix(answer.quizId) + "quizFinished").decode())):
        raise HTTPException(status_code=406, detail="No more questions for quiz with id " + str(answer.quizId) + "!")
    return (get_next_question(answer))


@CATModule.get("/quiz/result", summary="Get the result of quiz with ID", tags=["result"])
async def api_get_result(quizIdAPI: QuizIdAPI):
    """
    Get the result of the quiz by quizID:

    - **quizId**: Unique ID of the quiz (was returned by the POST quiz request).

    Response:
    - **quizId**: Unique ID of the quiz.
    - **quizFinished**: Shows if the quiz is already finished.
    - **currentCompetency**: Describes the proficiency of the examinee. For non-adaptive tests, this is the percentage of correct answers.
    - **measurementAccuracy**: Standard Estimation Error of the current competency (for adaptive tests). Has no meaning for non-adaptive tests.
    - **administeredQuestions**: An ordered list of of all the questions administered.
    - **responses**: An ordered list of the responses to the administered questions.
    - **maxNumberOfQuestions**: The maximum number of questions the quiz could have had.
    """
    if (not (quizIdExists(quizIdAPI.quizId))):
        raise HTTPException(status_code=404, detail="Quiz with id " + str(quizIdAPI.quizId) + " not found!")
    if r.get(get_rPrefix(quizIdAPI.quizId) + "questionSelector").decode("utf-8") == 'linearSelector' and (
            not (strtobool(r.get(get_rPrefix(quizIdAPI.quizId) + "quizFinished").decode()))):
        raise HTTPException(status_code=406,
                            detail="Quiz with id " + str(quizIdAPI.quizId) + " has not been finished yet!")
    return (get_result(quizIdAPI))


@CATModule.delete("/quiz", summary="Delete quiz with ID", tags=["quiz"])
async def api_delete_quiz(quizIdAPI: QuizIdAPI):
    """
    Delete the quiz with the defined quizId:

    - **quizId**: Unique ID of the quiz (was returned by the POST quiz request)

    Response:
    Status 200 OK if the quiz was successfully deleted.
    """
    if (not (quizIdExists(quizIdAPI.quizId))):
        raise HTTPException(status_code=404, detail="Quiz with id " + str(quizIdAPI.quizId) + " not found!")
    delete_quiz(quizIdAPI)
    return ("Quiz with id " + str(quizIdAPI.quizId) + " was successfully deleted!")


@CATModule.get("/", status_code=200)
async def get_status200():
    return ()


# --------------- Functionality ---------------

def create_quiz(quizAPI):  # Save the quiz in Redis
    quizAPI.quizId = id(quizAPI)  # create unique quizID

    # Save Data recieved from Call to Redis
    r.mset({get_rPrefix(quizAPI.quizId) + "maxNumberOfQuestions": quizAPI.maxNumberOfQuestions,
            get_rPrefix(quizAPI.quizId) + "minMeasurementAccuracy": quizAPI.minMeasurementAccuracy,
            get_rPrefix(quizAPI.quizId) + "inputProficiencyLevel": quizAPI.inputProficiencyLevel,
            get_rPrefix(quizAPI.quizId) + "questionSelector": quizAPI.questionSelector,
            get_rPrefix(quizAPI.quizId) + "competencyEstimator": quizAPI.competencyEstimator,
            get_rPrefix(quizAPI.quizId) + "standardErrorOfEstimation": config.defaultAdaptiveQuiz["standardErrorOfEstimation"],
            get_rPrefix(quizAPI.quizId) + "quizFinished": str(False)
            })

    for question in quizAPI.questions:  # Store questions in Redis
        r.rpush(get_rPrefix(quizAPI.quizId) + "questions", json.dumps(question.__dict__))

    # Initialization Initializer (If InputProficiencyLevel is 99.9, a random difficulty will be chosen.)
    init_initializer(quizAPI)

    # Initialization DifferentialEvolutionEstimator
    init_estimator(quizAPI)

    # Selector specific initializations
    init_selector(quizAPI)

    r.rpush("quizIds", quizAPI.quizId)

    return (quizAPI)


def get_next_question(answer: AnswerAPI):  # Calculate the next quiz question
    # Load Questions
    items = get_items(answer.quizId)
    administered_items = get_administeredItems(answer.quizId)
    # Define Stopping Criterion
    minErrorStopper = MinErrorStopper(float(r.get(get_rPrefix(answer.quizId) + "minMeasurementAccuracy")))  # Describes the measurement accuracy threshold of the exam --> standard error of estimation is used.
    maxItemStopper = MaxItemStopper(int(r.get(get_rPrefix(answer.quizId) + "maxNumberOfQuestions")))

    selector = get_selector(answer.quizId)

    if len(administered_items) == 0:  # Select first question and deliver it
        itemIndex = selector.select(items=get_items(answer.quizId), # maps cat-sim index to question id
                                    administered_items=administered_items, # all answered questions
                                    est_theta=float(r.get(get_rPrefix(answer.quizId) + "estTheta"))) # est_theta is the current compentce level
        r.set(get_rPrefix(answer.quizId) + "itemIndex", int(itemIndex))

        nextQuestion = NextQuestionAPI(quizId=answer.quizId,
                                       questionId=get_questionId_by_index(answer.quizId, itemIndex),
                                       measurementAccuracy=float(r.get(get_rPrefix(answer.quizId) + "standardErrorOfEstimation")),
                                       currentCompetency=(float(r.get(get_rPrefix(answer.quizId) + "estTheta"))),
                                       quizFinished=strtobool(r.get(get_rPrefix(answer.quizId) + "quizFinished").decode()))
        r.rpush(get_rPrefix(answer.quizId) + "administeredItems", int(itemIndex))
    elif answer.isCorrect != None and answer.isCorrect >= 0.0 and answer.isCorrect <= 1.0:  # Check if input is okay -> TODO move to API method and throw HTTPException if value is wrong
        r.rpush(get_rPrefix(answer.quizId) + "responses", answer.isCorrect)  # Add response to List

        estimator = get_estimator(answer.quizId)

        estTheta = estimator.estimate(items=items,
                                      administered_items=administered_items,
                                      response_vector=get_responses(answer.quizId),
                                      est_theta=float(r.get(get_rPrefix(answer.quizId) + "estTheta")))
        r.set(get_rPrefix(answer.quizId) + "estTheta", estTheta)

        standardErrorOfEstimation = irt.see(theta=estTheta, items=items[administered_items])
        r.set(get_rPrefix(answer.quizId) + "standardErrorOfEstimation", standardErrorOfEstimation)

        quizFinished = (minErrorStopper.stop(administered_items=items[administered_items], theta=estTheta) or (maxItemStopper.stop(administered_items=items[administered_items])))
        r.set(get_rPrefix(answer.quizId) + "quizFinished", str(quizFinished))

        if (not (quizFinished)):
            itemIndex = selector.select(items=get_items(answer.quizId),
                                        administered_items=administered_items,
                                        est_theta=estTheta)
            r.set(get_rPrefix(answer.quizId) + "itemIndex", int(itemIndex))

            nextQuestion = NextQuestionAPI(quizId=answer.quizId,
                                           questionId=get_questionId_by_index(answer.quizId, itemIndex),
                                           measurementAccuracy=standardErrorOfEstimation,
                                           currentCompetency=estTheta,
                                           quizFinished=quizFinished)
            r.rpush(get_rPrefix(answer.quizId) + "administeredItems", int(itemIndex))
        else: # if quiz is already finished return no new questionId
            nextQuestion = NextQuestionAPI(quizId=answer.quizId,
                                           questionId=None,
                                           measurementAccuracy=standardErrorOfEstimation,
                                           currentCompetency=estTheta,
                                           quizFinished=quizFinished)
    return (nextQuestion)


def get_result(quizIdAPI: QuizIdAPI):
    if r.get(get_rPrefix(quizIdAPI.quizId) + "questionSelector").decode("utf-8") == 'linearSelector': #get the result of a non-adaptive quiz
        responses = get_responses_as_float(quizIdAPI.quizId)
        r.set(get_rPrefix(quizIdAPI.quizId) + "standardErrorOfEstimation", 0.0)
        #needed to calculate percentage of correct answers
        achievablePoints = 0.0
        achievedPoints = 0.0
        i = 0
        administeredQuestions: List[QuestionAPI] = []  # create list of quiz questions with their real questionID.
        for itemIndex in get_administeredItems(quizIdAPI.quizId):
            item = get_item_by_index(quizIdAPI.quizId, itemIndex)
            questionAPI = QuestionAPI(id=get_questionId_by_index(quizIdAPI.quizId, itemIndex), discrimination=item[0],
                                      difficulty=item[1], pseudoGuessing=item[2], upperAsymptote=item[3])
            administeredQuestions.append(questionAPI)
            achievablePoints = achievablePoints + item[1]
            achievedPoints = achievedPoints + item[1] * responses[i]
            i = i + 1
        r.set(get_rPrefix(quizIdAPI.quizId) + "estTheta", achievedPoints / achievablePoints)
        result = ResultAPI(quizId=quizIdAPI.quizId,
                           quizFinished=strtobool(r.get(get_rPrefix(quizIdAPI.quizId) + "quizFinished").decode()),
                           currentCompetency=float(r.get(get_rPrefix(quizIdAPI.quizId) + "estTheta")),
                           measurementAccuracy=float(r.get(get_rPrefix(quizIdAPI.quizId) + "standardErrorOfEstimation")),
                           administeredQuestions=administeredQuestions,
                           responses=get_responses_as_float(quizIdAPI.quizId).tolist(),
                           maxNumberOfQuestions=int(r.get(get_rPrefix(quizIdAPI.quizId) + "maxNumberOfQuestions")))
    else: #get the result of an adaptive quiz
        administeredQuestions: List[QuestionAPI] = []  # create list of quiz questions with their real questionID.
        for itemIndex in get_administeredItems(quizIdAPI.quizId):
            item = get_item_by_index(quizIdAPI.quizId, itemIndex)
            questionAPI = QuestionAPI(id=get_questionId_by_index(quizIdAPI.quizId, itemIndex), discrimination=item[0],
                                      difficulty=item[1], pseudoGuessing=item[2], upperAsymptote=item[3])
            administeredQuestions.append(questionAPI)
        result = ResultAPI(quizId=quizIdAPI.quizId,
                           quizFinished=strtobool(r.get(get_rPrefix(quizIdAPI.quizId) + "quizFinished").decode()),
                           currentCompetency=float(r.get(get_rPrefix(quizIdAPI.quizId) + "estTheta")),
                           measurementAccuracy=float(r.get(get_rPrefix(quizIdAPI.quizId) + "standardErrorOfEstimation")),
                           administeredQuestions=administeredQuestions,
                           responses=get_responses_as_float(quizIdAPI.quizId).tolist(),
                           maxNumberOfQuestions=int(r.get(get_rPrefix(quizIdAPI.quizId) + "maxNumberOfQuestions")))
    return result


def delete_quiz(quizIdAPI):
    r.delete(get_rPrefix(quizIdAPI.quizId) + "maxNumberOfQuestions",
             get_rPrefix(quizIdAPI.quizId) + "minMeasurementAccuracy",
             get_rPrefix(quizIdAPI.quizId) + "inputProficiencyLevel",
             get_rPrefix(quizIdAPI.quizId) + "questionSelector",
             get_rPrefix(quizIdAPI.quizId) + "competencyEstimator",
             get_rPrefix(quizIdAPI.quizId) + "standardErrorOfEstimation",
             get_rPrefix(quizIdAPI.quizId) + "quizFinished",
             get_rPrefix(quizIdAPI.quizId) + "minDiff",
             get_rPrefix(quizIdAPI.quizId) + "maxDiff",
             get_rPrefix(quizIdAPI.quizId) + "questions",
             get_rPrefix(quizIdAPI.quizId) + "estTheta")
    r.lrem("quizIds", 0, quizIdAPI.quizId)
    return


# --------------- Helper Methods ---------------

def get_rPrefix(quizId: int):  # Helper method to create the naming for the database.
    return (str(quizId) + "_")


def get_items(quizId: int):  # Helper method to load all questions into a catsim-usable np array
    questionsJSON = r.lrange(get_rPrefix(quizId) + "questions", 0, r.llen(get_rPrefix(quizId) + "questions"))
    items = np.empty([0, 4], float)  # contains all possible questions for the quiz in the catsim format
    for questionJSON in questionsJSON:
        questionParsed = json.loads(questionJSON)
        items = np.append(items, [[questionParsed.get('discrimination'), questionParsed.get('difficulty'),
                                   questionParsed.get('pseudoGuessing'), questionParsed.get('upperAsymptote')]], 0)
    return items


def get_item_by_index(quizId: int, itemIndex: int):
    items = get_items(quizId)
    return (items[itemIndex])


def get_questionIds(quizId: int):  # Helper method to load all questionIds into a list, so we can use the listindex to select the chosen question id
    questionsJSON = r.lrange(get_rPrefix(quizId) + "questions", 0, r.llen(get_rPrefix(quizId) + "questions"))
    questionIds = []  # contains all the real questionIds; maps to items via the index
    for questionJSON in questionsJSON:
        questionParsed = json.loads(questionJSON)
        questionIds.append(questionParsed.get('id'))
    return questionIds


def get_questionId_by_index(quizId: int, itemIndex: int):  # Helper method to retrieve a question id by its index
    questionIds = get_questionIds(quizId)
    return (questionIds[itemIndex])


def get_administeredItems(quizId: int):
    administeredItemsJSON = r.lrange(get_rPrefix(quizId) + "administeredItems", 0, r.llen(get_rPrefix(quizId) + "administeredItems"))
    administeredItems = np.empty([0, 1], int)
    for administeredItemJSON in administeredItemsJSON:
        administeredItems = np.append(administeredItems, int(administeredItemJSON))
    return administeredItems


def get_responses(quizId: int):
    responsesJSON = r.lrange(get_rPrefix(quizId) + "responses", 0, r.llen(get_rPrefix(quizId) + "responses"))
    responses = np.empty([0, 1], dtype=bool)  # contains the given answers for the administeredQuestions as boolean values (needed for the catsim library)
    for responseJSON in responsesJSON:
        if (float(responseJSON) == 1.0):
            responses = np.append(responses, True)
        else:
            responses = np.append(responses, False)
    return responses


def get_responses_as_float(quizId: int):
    responsesJSON = r.lrange(get_rPrefix(quizId) + "responses", 0, r.llen(get_rPrefix(quizId) + "responses"))
    responses = np.empty([0, 1], dtype=float)  # contains the given answers for the administeredQuestions as float values
    for responseJSON in responsesJSON:
        responses = np.append(responses, float(responseJSON))
    return responses


def get_indices(quizId: int):  # Helper method for non-adaptive quizzes.
    questions = get_items(quizId)
    indices = []
    i = 0
    while i <= len(questions):
        indices.append(i)
        i = i + 1
    return indices


def get_estimator(quizId: int):
    competencyEstimator = r.get(get_rPrefix(quizId) + "competencyEstimator").decode("utf-8")
    if competencyEstimator == "differentialEvolutionEstimator":
        estimator = DifferentialEvolutionEstimator(
            (float(r.get(get_rPrefix(quizId) + "minDiff")), float(r.get(get_rPrefix(quizId) + "maxDiff"))))
    return estimator


def get_selector(quizId: int):
    questionSelector = r.get(get_rPrefix(quizId) + "questionSelector").decode("utf-8")
    if questionSelector == 'maxInfoSelector':
        selector = MaxInfoSelector()
    elif questionSelector == 'linearSelector':
        selector = LinearSelector(get_indices(quizId))
    return (selector)


def quizIdExists(quizId: int):
    quizIdsJSON = r.lrange("quizIds", 0, r.llen("quizIds"))
    for quizIdJSON in quizIdsJSON:
        if (int(quizIdJSON) == quizId):
            return True
    return False


# INIT Methods for CAT-SIM Objects
def init_estimator(quizAPI: QuizAPI):
    if quizAPI.competencyEstimator == 'differentialEvolutionEstimator':
        minInColumns = numpy.amin(get_items(quizAPI.quizId), axis=0)
        minDiff = minInColumns[1]
        maxInColumns = numpy.amax(get_items(quizAPI.quizId), axis=0)
        maxDiff = maxInColumns[1]
        r.mset({get_rPrefix(quizAPI.quizId) + "minDiff": minDiff,
                get_rPrefix(quizAPI.quizId) + "maxDiff": maxDiff
                })
    # could implement other estimators with other parameters
    return


def init_selector(quizAPI: QuizAPI):
    # this implements: going through all questions in the given order and stop after the last one (because minMeasurementAccuracy=0)
    if quizAPI.questionSelector == 'linearSelector':
        quizAPI.maxNumberOfQuestions = len(quizAPI.questions)
        r.set(get_rPrefix(quizAPI.quizId) + "maxNumberOfQuestions",
              len(quizAPI.questions))  # a classic quiz will stop after all its items are delivered
        quizAPI.minMeasurementAccuracy = 0.0
        r.set(get_rPrefix(quizAPI.quizId) + "minMeasurementAccuracy",
              0.0)  # Is set to 0.0 since a non-adaptive quiz should display all questions
        quizAPI.competencyEstimator = "linearEstimator"
    # could implement other selectors with other parameters
    return


def init_initializer(quizAPI: QuizAPI):
    if quizAPI.inputProficiencyLevel == 99.9: # 99.9: magic value to initialize with random proficiency
        initializer = RandomInitializer()  # Initialize quiz with random proficiency level
    else:
        initializer = FixedPointInitializer(
            quizAPI.inputProficiencyLevel)  # Initialize quiz with given proficiency level
    currentProficiencyLevel = initializer.initialize()
    r.set(get_rPrefix(quizAPI.quizId) + "estTheta", currentProficiencyLevel)
    return
