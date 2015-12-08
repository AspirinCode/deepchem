"""
Top level script to featurize input, train models, and evaluate them.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals
import argparse
import os
from deep_chem.utils.featurize import generate_directories
from deep_chem.utils.featurize import extract_data
from deep_chem.utils.featurize import generate_targets
from deep_chem.utils.featurize import generate_features
from deep_chem.utils.featurize import generate_vs_utils_features
from deep_chem.models.standard import fit_singletask_models
from deep_chem.utils.load import process_datasets
from deep_chem.utils.load import transform_data
from deep_chem.utils.evaluate import results_to_csv
from deep_chem.utils.save import save_model
from deep_chem.utils.save import load_model
from deep_chem.utils.save import save_sharded_dataset
from deep_chem.utils.save import load_sharded_dataset
from deep_chem.utils.evaluate import compute_model_performance

def add_featurization_command(subparsers):
  """Adds flags for featurize subcommand."""
  featurize_cmd = subparsers.add_parser(
      "featurize", help="Featurize raw input data.")
  add_featurize_group(featurize_cmd)

def add_featurize_group(featurize_cmd):
  """Adds flags for featurizization."""
  featurize_group = featurize_cmd.add_argument_group("Input Specifications")
  featurize_group.add_argument(
      "--input-files", required=1, nargs="+",
      help="Input file with data.")
  featurize_group.add_argument(
      "--input-type", default="csv",
      choices=["csv", "pandas", "sdf"],
      help="Type of input file. If pandas, input must be a joblib\n"
           "containing a pandas dataframe. If sdf, should be in\n"
           "(perhaps gzipped) sdf file.")
  featurize_group.add_argument(
      "--delimiter", default=",", type=str,
      help="If csv input, delimiter to use for read csv file")
  featurize_group.add_argument(
      "--fields", required=1, nargs="+",
      help="Names of fields.")
  featurize_group.add_argument(
      "--field-types", required=1, nargs="+",
      choices=["string", "float", "list-string", "list-float", "ndarray"],
      help="Type of data in fields.")
  featurize_group.add_argument(
      "--feature-fields", type=str, nargs="+",
      help="Optional field that holds pre-computed feature vector")
  featurize_group.add_argument(
      "--target-fields", type=str, nargs="+", required=1,
      help="Name of measured field to predict.")
  featurize_group.add_argument(
      "--split-field", type=str, default=None,
      help="Name of field specifying train/test split.")
  featurize_group.add_argument(
      "--smiles-field", type=str, default="smiles",
      help="Name of field specifying SMILES for molecule.")
  featurize_group.add_argument(
      "--id-field", type=str, default=None,
      help="Name of field specifying unique identifier for molecule.\n"
           "If none is specified, then smiles-field is used as identifier.")
  # TODO(rbharath): This should be moved to train-tests-split
  featurize_group.add_argument(
      "--threshold", type=float, default=None,
      help="If specified, will be used to binarize real-valued target-fields.")
  featurize_group.add_argument(
      "--name", required=1,
      help="Name of the dataset.")
  featurize_group.add_argument(
      "--out", required=1,
      help="Folder to generate processed dataset in.")
  featurize_group.set_defaults(func=featurize_input)

def add_train_test_command(subparsers):
  """Adds flags for train-test-split subcommand."""
  train_test_cmd = subparsers.add_parser(
      "train-test-split",
      help="Apply standard data transforms to raw features generated by featurize,\n"
           "then split data into train/test and store data as (X,y) matrices.")
  train_test_cmd.add_argument(
      "--input-transforms", nargs="+", default=[],
      choices=["normalize-and-truncate"],
      help="Transforms to apply to input data.")
  train_test_cmd.add_argument(
      "--output-transforms", type=str, default="",
      help="Comma-separated list (no spaces) of transforms to apply to output data.\n"
           "Supported transforms are 'log' and 'normalize'. 'None' will be taken\n"
           "to mean no transforms are required.")
  train_test_cmd.add_argument(
      "--feature-types", type=str, required=1,
      help="Comma-separated list (no spaces) of types of featurizations to use.\n"
           "Each featurization must correspond to subdirectory in generated\n"
           "data directory.")
  train_test_cmd.add_argument(
      "--paths", nargs="+", required=1,
      help="Paths to input datasets.")
  train_test_cmd.add_argument(
      "--splittype", type=str, default="scaffold",
      choices=["scaffold", "random", "specified"],
      help="Type of train/test data-splitting. 'scaffold' uses Bemis-Murcko scaffolds.\n"
           "specified requires that split be in original data.")
  train_test_cmd.add_argument(
      "--weight-positives", type=bool, default=False,
      help="Weight positive examples to have same total weight as negatives.")
  train_test_cmd.add_argument(
      "--mode", default="singletask",
      choices=["singletask", "multitask"],
      help="Type of model being built.")
  train_test_cmd.add_argument(
      "--train-out", type=str, required=1,
      help="Location to save train set.")
  train_test_cmd.add_argument(
      "--test-out", type=str, required=1,
      help="Location to save test set.")
  train_test_cmd.set_defaults(func=train_test_input)

def add_model_group(fit_cmd):
  """Adds flags for specifying models."""
  group = fit_cmd.add_argument_group("model")
  group.add_argument(
      "--model", required=1,
      choices=["logistic", "rf_classifier", "rf_regressor",
               "linear", "ridge", "lasso", "lasso_lars", "elastic_net",
               "singletask_deep_network", "multitask_deep_network", "3D_cnn"],
      help="Type of model to build. Some models may allow for\n"
           "further specification of hyperparameters. See flags below.")

  group = fit_cmd.add_argument_group("Neural Net Parameters")
  group.add_argument(
      "--n-hidden", type=int, default=500,
      help="Number of hidden neurons for NN models.")
  group.add_argument(
      "--learning-rate", type=float, default=0.01,
      help="Learning rate for NN models.")
  group.add_argument(
      "--dropout", type=float, default=0.5,
      help="Learning rate for NN models.")
  group.add_argument(
      "--n-epochs", type=int, default=50,
      help="Number of epochs for NN models.")
  group.add_argument(
      "--batch-size", type=int, default=32,
      help="Number of examples per minibatch for NN models.")
  group.add_argument(
      "--loss-function", type=str, default="mean_squared_error",
      help="Loss function type.")
  group.add_argument(
      "--decay", type=float, default=1e-4,
      help="Learning rate decay for NN models.")
  group.add_argument(
      "--validation-split", type=float, default=0.0,
      help="Percent of training data to use for validation.")


def add_fit_command(subparsers):
  """Adds arguments for fit subcommand."""
  fit_cmd = subparsers.add_parser(
      "fit", help="Fit a model to training data.")
  group = fit_cmd.add_argument_group("load-and-transform")
  group.add_argument(
      "--task-type", required=1,
      choices=["classification", "regression"],
      help="Type of learning task.")
  group.add_argument(
      "--saved-data", required=1,
      help="Location of saved transformed data.")
  add_model_group(fit_cmd)
  group = fit_cmd.add_argument_group("save")
  group.add_argument(
      "--saved-out", type=str, required=1,
      help="Location to save trained model.")
  fit_cmd.set_defaults(func=fit_model)


def add_eval_command(subparsers):
  """Adds arguments for eval subcommand."""
  eval_cmd = subparsers.add_parser(
      "eval",
      help="Evaluate trained model on test data processed by transform.")
  group = eval_cmd.add_argument_group("load model/data")
  group.add_argument(
      "--saved-model", type=str, required=1,
      help="Location from which to load saved model.")
  group.add_argument(
      "--saved-data", required=1, help="Location of saved transformed data.")
  group.add_argument(
      "--modeltype", required=1,
      choices=["sklearn", "keras-graph", "keras-sequential"],
      help="Type of model to load.")
  # TODO(rbharath): This argument seems a bit extraneous. Is it really
  # necessary?
  group.add_argument(
      "--task-type", required=1,
      choices=["classification", "regression"],
      help="Type of learning task.")
  group = eval_cmd.add_argument_group("Classification metrics")
  group.add_argument(
      "--compute-aucs", action="store_true", default=False,
      help="Compute AUC for trained models on test set.")
  group.add_argument(
      "--compute-accuracy", action="store_true", default=False,
      help="Compute accuracy for trained models on test set.")
  group.add_argument(
      "--compute-recall", action="store_true", default=False,
      help="Compute recall for trained models on test set.")
  group.add_argument(
      "--compute-matthews-corrcoef", action="store_true", default=False,
      help="Compute Matthews Correlation Coefficient for trained models on test set.")

  group = eval_cmd.add_argument_group("Regression metrics")
  group.add_argument(
      "--compute-r2s", action="store_true", default=False,
      help="Compute R^2 for trained models on test set.")
  group.add_argument(
      "--compute-rms", action="store_true", default=False,
      help="Compute RMS for trained models on test set.")

  eval_cmd.add_argument(
      "--csv-out", type=str, required=1,
      help="Outputted predictions on evaluated set.")
  eval_cmd.add_argument(
      "--stats-out", type=str, required=1j,
      help="Computed statistics on evaluated set.")
  eval_cmd.set_defaults(func=eval_trained_model)

# TODO(rbharath): There are a lot of duplicate commands introduced here. Is
# there a nice way to factor them?
def add_model_command(subparsers):
  """Adds flags for model subcommand."""
  model_cmd = subparsers.add_parser(
      "model", help="Combines featurize, train-test-split, fit, eval into one\n"
      "command for user convenience.")
  model_cmd.add_argument(
      "--skip-featurization", action="store_true",
      help="If set, skip the featurization step.")
  model_cmd.add_argument(
      "--skip-train-test-split", action="store_true",
      help="If set, skip the train-test-split step.")
  model_cmd.add_argument(
      "--skip-fit", action="store_true",
      help="If set, skip model fit step.")
  add_featurize_group(model_cmd)

  train_test_group = model_cmd.add_argument_group("train_test_group")
  train_test_group.add_argument(
      "--input-transforms", nargs="+", default=[],
      choices=["normalize-and-truncate"],
      help="Transforms to apply to input data.")
  train_test_group.add_argument(
      "--output-transforms", type=str, default="",
      help="Comma-separated list (no spaces) of transforms to apply to output data.\n"
           "Supported transforms are log and normalize.")
  train_test_group.add_argument(
      "--mode", default="singletask",
      choices=["singletask", "multitask"],
      help="Type of model being built.")
  train_test_group.add_argument(
      "--feature-types", type=str, required=1,
      help="Comma-separated list (no spaces) of types of featurizations to use.\n"
           "Each featurization must correspond to subdirectory in generated\n"
           "data directory.")
  train_test_group.add_argument(
      "--splittype", type=str, default="scaffold",
      choices=["scaffold", "random", "specified"],
      help="Type of train/test data-splitting. 'scaffold' uses Bemis-Murcko scaffolds.\n"
           "specified requires that split be in original data.")

  add_model_group(model_cmd)
  model_cmd.add_argument(
      "--task-type", default="classification",
      choices=["classification", "regression"],
      help="Type of learning task.")
  model_cmd.set_defaults(func=create_model)

def create_model(args):
  """Creates a model"""
  data_dir = os.path.join(args.out, args.name)
  print("+++++++++++++++++++++++++++++++++")
  print("Perform featurization")
  if not args.skip_featurization:
    _featurize_input(
        args.name, args.out, args.input_file, args.input_type, args.fields,
        args.field_types, args.feature_fields, args.target_fields,
        args.smiles_field, args.split_field, args.id_field, args.threshold,
        args.delimiter)

  print("+++++++++++++++++++++++++++++++++")
  print("Perform train-test split")
  paths = [data_dir]
  train_out = os.path.join(data_dir, "%s-train.joblib" % args.name)
  test_out = os.path.join(data_dir, "%s-test.joblib" % args.name)
  if not args.skip_train_test_split:
    _train_test_input(
        paths, args.output_transforms, args.input_transforms, args.feature_types,
        args.splittype, args.mode, train_out, test_out,
        args.target_fields)

  print("+++++++++++++++++++++++++++++++++")
  print("Fit model")
  modeltype = get_model_type(args.model)
  extension = get_model_extension(modeltype)
  saved_out = os.path.join(data_dir, "%s.%s" % (args.model, extension))
  if not args.skip_fit:
    _fit_model(
        args.model, args.task_type, args.n_hidden, args.learning_rate,
        args.dropout, args.n_epochs, args.decay, args.batch_size, args.loss_function,
        args.validation_split, saved_out, train_out, args.target_fields)


  print("+++++++++++++++++++++++++++++++++")
  print("Eval Model on Train")
  print("-------------------")
  csv_out_train = os.path.join(data_dir, "%s-train.csv" % args.name)
  stats_out_train = os.path.join(data_dir, "%s-train-stats.txt" % args.name)
  csv_out_test = os.path.join(data_dir, "%s-test.csv" % args.name)
  stats_out_test = os.path.join(data_dir, "%s-test-stats.txt" % args.name)
  compute_aucs, compute_recall, compute_accuracy, compute_matthews_corrcoef = (
      False, False, False, False)
  compute_r2s, compute_rms = False, False
  if args.task_type == "classification":
    compute_aucs, compute_recall, compute_accuracy, compute_matthews_corrcoef = (
        True, True, True, True)
  elif args.task_type == "regression":
    compute_r2s, compute_rms = True, True
  _eval_trained_model(
      modeltype, saved_out, train_out, args.task_type, compute_aucs,
      compute_recall, compute_accuracy, compute_matthews_corrcoef, compute_r2s,
      compute_rms, csv_out_train, stats_out_train, args.target_fields)
  print("Eval Model on Test")
  print("------------------")
  _eval_trained_model(
      modeltype, saved_out, test_out, args.task_type, compute_aucs,
      compute_recall, compute_accuracy, compute_matthews_corrcoef, compute_r2s,
      compute_rms, csv_out_test, stats_out_test, args.target_fields)

def parse_args(input_args=None):
  """Parse command-line arguments."""
  parser = argparse.ArgumentParser()
  subparsers = parser.add_subparsers(title='Modes')

  add_featurization_command(subparsers)
  add_train_test_command(subparsers)
  add_fit_command(subparsers)
  add_eval_command(subparsers)

  add_model_command(subparsers)

  return parser.parse_args(input_args)

def featurize_input(args):
  """Wrapper function that calls _featurize_input with args unwrapped."""
  _featurize_inputs(
      args.name, args.out, args.input_file, args.input_type, args.fields,
      args.field_types, args.feature_fields, args.target_fields,
      args.smiles_field, args.split_field, args.id_field, args.threshold,
      args.delimiter)


#make this helper and add a wrapper function that has "input files" and add multiprocessing option
#shard into 10x at this step (make a flag)
'''
def _featurize_input(input_file, name, out, input_type, fields, field_types,
                     feature_fields, prediction_field, smiles_field,
'''
def _featurize_input(name, out, input_file, input_type, fields, field_types,
                     feature_fields, target_fields, smiles_field,
                     split_field, id_field, threshold, delimiter):
  """Featurizes raw input data."""
  if len(fields) != len(field_types):
    raise ValueError("number of fields does not equal number of field types")
  if id_field is None:
    id_field = smiles_field
    '''
  out_x_joblib, out_y_joblib = generate_directories(name, input_file, out, feature_fields)
  df, mols = extract_data(
      input_file, input_type, fields, field_types, prediction_field,
      smiles_field, threshold, delimiter)
  print "Generating targets"
  generate_targets(df, prediction_field, split_field,
                   smiles_field, id_field, out_y_joblib)
  print "Generating user-specified features"
  generate_features(df, feature_fields, smiles_field, id_field, out_x_joblib)
  print "Generating circular fingerprints"
  generate_vs_utils_features(df, name, input_file, out, smiles_field, id_field, "fingerprints")
  print "Generating rdkit descriptors"
  generate_vs_utils_features(df, name, input_file, out, smiles_field, id_field, "descriptors")

def _featurize_inputs(name, out, input_files, input_type, fields, field_types,
                     feature_fields, prediction_field, smiles_field,
                     split_field, id_field, threshold, delimiter):
  
  other_arguments = (name, out, input_type, fields, field_types,
                     feature_fields, prediction_field, smiles_field,
                     split_field, id_field, threshold, delimiter)
  pool = mp.Pool(mp.cpu_count())
  pool.map(_featurize_input, itertools.izip(input_files, itertools.repeat(other_arguments)))
  pool.terminate()
  
  '''
  out_x_pkl, out_y_pkl = generate_directories(name, out, feature_fields)
  df, _ = extract_data(
      input_file, input_type, fields, field_types, target_fields,
      smiles_field, threshold, delimiter)
  print("Generating targets")
  generate_targets(df, target_fields, split_field,
                   smiles_field, id_field, out_y_pkl)
  print("Generating user-specified features")
  generate_features(df, feature_fields, smiles_field, id_field, out_x_pkl)
  print("Generating circular fingerprints")
  generate_vs_utils_features(df, name, out, smiles_field, id_field, "fingerprints")
  print("Generating rdkit descriptors")
  generate_vs_utils_features(df, name, out, smiles_field, id_field, "descriptors")

def train_test_input(args):
  """Wrapper function that calls _train_test_input after unwrapping args."""
  _train_test_input(
      args.paths, args.output_transforms, args.input_transforms,
      args.feature_types, args.splittype, args.mode,
      args.train_out, args.test_out, args.target_fields)

#decompose this into: a) compute train test split using only smiles.  b) for each shard, make a train test numpy array 
def _train_test_input(paths, output_transforms, input_transforms,
                      feature_types, splittype, mode,
                      train_out, test_out, target_names):
  """Saves transformed model."""
  if output_transforms == "" or output_transforms == "None":
    output_transforms = []
  else:
    output_transforms = output_transforms.split(",")
  feature_types = feature_types.split(",")
  print("About to process_dataset")
  train_dict, test_dict = process_datasets(
      paths, feature_types=feature_types, splittype=splittype,
      mode=mode, target_names=target_names)
  print("Finished process_dataset")

  print("Starting transform_data")
  trans_train_dict = transform_data(
      train_dict, input_transforms, output_transforms)
  print("Finished transform_data on train")
  trans_test_dict = transform_data(test_dict, input_transforms, output_transforms)
  print("Finished transform_data on test")
  transforms = {"input_transforms": input_transforms,
                "output_transform": output_transforms}
  stored_train = {"raw": train_dict,
                  "transformed": trans_train_dict,
                  "transforms": transforms}
  stored_test = {"raw": test_dict,
                 "transformed": trans_test_dict,
                 "transforms": transforms}
  print("About to save dataset..")
  save_sharded_dataset(stored_train, train_out)
  save_sharded_dataset(stored_test, test_out)

def _train_test_inputs(paths, output_transforms, input_transforms,
                      feature_types, splittype, weight_positives, mode,
                      train_out, test_out):

def fit_model(args):
  """Wrapper that calls _fit_model with arguments unwrapped."""
  # TODO(rbharath): Bundle these arguments up into a training_params dict.
  _fit_model(
      args.model, args.task_type, args.n_hidden,
      args.learning_rate, args.dropout, args.n_epochs, args.decay,
      args.batch_size, args.loss_function, args.validation_split,
      args.saved_out, args.saved_data, args.target_fields)

def _fit_model(model, task_type, n_hidden, learning_rate, dropout,
               n_epochs, decay, batch_size, loss_function, validation_split, saved_out,
               saved_data, target_names):
  """Builds model from featurized data."""
  task_types = {target: task_type for target in target_names}

  stored_train = load_sharded_dataset(saved_data)
  train_dict = stored_train["transformed"]

  if model == "singletask_deep_network":
    from deep_chem.models.deep import fit_singletask_mlp
    models = fit_singletask_mlp(
        train_dict, task_types, n_hidden=n_hidden, learning_rate=learning_rate,
        dropout=dropout, nb_epoch=n_epochs, decay=decay, batch_size=batch_size,
        validation_split=validation_split)
  elif model == "multitask_deep_network":
    from deep_chem.models.deep import fit_multitask_mlp
    models = fit_multitask_mlp(
        train_dict, task_types, n_hidden=n_hidden, learning_rate=learning_rate,
        dropout=dropout, batch_size=batch_size, nb_epoch=n_epochs, decay=decay,
        validation_split=validation_split)
  elif model == "3D_cnn":
    from deep_chem.models.deep3d import fit_3D_convolution
    models = fit_3D_convolution(
        train_dict, nb_epoch=n_epochs, batch_size=batch_size,
        learning_rate=learning_rate, loss_function=loss_function)
  else:
    models = fit_singletask_models(train_dict, model)
  modeltype = get_model_type(model)
  save_model(models, modeltype, saved_out)

def get_model_type(model):
  """Associate each model with a modeltype (used for saving/loading)."""
  if model in ["singletask_deep_network", "multitask_deep_network"]:
    modeltype = "keras-graph"
  elif model in ["3D_cnn"]:
    modeltype = "keras-sequential"
  elif model == "neural_fingerprint":
    modeltype = "autograd"
  else:
    modeltype = "sklearn"
  return modeltype

def get_model_extension(modeltype):
  """Get the saved filetype extension for various types of models."""
  if modeltype == "sklearn":
    return "joblib"
  elif modeltype == "autograd":
    return "joblib.gz"
  elif modeltype == "keras-graph" or modeltype == "keras-sequential":
    return "h5"

def eval_trained_model(args):
  """Wrapper function that calls _eval_trained_model with unwrapped args."""
  _eval_trained_model(
      args.modeltype, args.saved_model, args.saved_data,
      args.task_type, args.compute_aucs, args.compute_recall,
      args.compute_accuracy, args.compute_matthews_corrcoef, args.compute_r2s,
      args.compute_rms, args.csv_out, args.stats_out,
      args.target_fields)

def _eval_trained_model(modeltype, saved_model, saved_data, task_type,
                        compute_aucs, compute_recall, compute_accuracy,
                        compute_matthews_corrcoef, compute_r2s, compute_rms,
                        csv_out, stats_out, target_names):
  """Evaluates a trained model on specified data."""
  model = load_model(modeltype, saved_model)
  task_types = {target: task_type for target in target_names}

  stored_test = load_sharded_dataset(saved_data)
  test_dict = stored_test["transformed"]
  raw_test_dict = stored_test["raw"]
  output_transforms = stored_test["transforms"]["output_transform"]

  with open(stats_out, "wb") as stats_file:
    results, _, _, _ = compute_model_performance(
        raw_test_dict, test_dict, task_types, model, modeltype,
        output_transforms, aucs=compute_aucs, r2s=compute_r2s, rms=compute_rms,
        recall=compute_recall, accuracy=compute_accuracy,
        mcc=compute_matthews_corrcoef, print_file=stats_file)
  with open(stats_out, "r") as stats_file:
    print(stats_file.read())
  results_to_csv(results, csv_out, task_type=task_type)

def main():
  """Invokes argument parser."""
  args = parse_args()
  args.func(args)

if __name__ == "__main__":
  main()
